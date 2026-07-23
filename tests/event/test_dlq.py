import pytest

from pymidil.event.dlq import SQSDlqRedriver
from pymidil.event.message import Message
from pymidil.event.observability import EventStatus, TelemetryDispatchHook
from pymidil.event.observability.sinks.base import TelemetrySink

pytestmark = pytest.mark.anyio


class ListSink(TelemetrySink):
    def __init__(self) -> None:
        self.events: list = []

    async def emit(self, envelope) -> None:
        self.events.append(envelope)


# ---- A4: dlq telemetry emission ----
async def test_on_dead_letter_emits_dlq_envelope():
    sink = ListSink()
    hook = TelemetryDispatchHook(sink, source_service="settlement-svc", broker="sqs")

    await hook.on_dead_letter(
        Message(
            id="EVT-9",
            body={"tx": "TX-1"},
            metadata={"event_type": "SettlementInitiated"},
        ),
        "sqs",
        error=RuntimeError("pool exhausted"),
    )

    env = sink.events[0]
    assert env.status == EventStatus.DLQ
    assert env.event_type == "SettlementInitiated"
    assert env.failure_reason == "pool exhausted"
    assert env.failure_class == "RuntimeError"


async def test_on_dead_letter_without_error_defaults_reason():
    sink = ListSink()
    hook = TelemetryDispatchHook(sink, source_service="svc")
    await hook.on_dead_letter(Message(id="m", body={}), "sqs")
    assert sink.events[0].status == EventStatus.DLQ
    assert sink.events[0].failure_class == "DeadLetter"


# ---- A4: SQS redrive primitive ----
class _FakeSqsClient:
    def __init__(self, messages: list) -> None:
        self._messages = messages
        self.sent: list = []
        self.deleted: list = []

    async def receive_message(self, **_kwargs):
        msgs, self._messages = self._messages, []
        return {"Messages": msgs}

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)

    async def delete_message(self, **kwargs):
        self.deleted.append(kwargs)


class _FakeClientCtx:
    def __init__(self, client: _FakeSqsClient) -> None:
        self._client = client

    async def __aenter__(self) -> _FakeSqsClient:
        return self._client

    async def __aexit__(self, *_exc) -> bool:
        return False


class _FakeSession:
    def __init__(self, client: _FakeSqsClient) -> None:
        self._client = client

    def client(self, *_args, **_kwargs) -> _FakeClientCtx:
        return _FakeClientCtx(self._client)


async def test_sqs_redrive_moves_messages_to_source():
    client = _FakeSqsClient(
        [
            {
                "Body": '{"booking_id": "BK-1"}',
                "ReceiptHandle": "rh-1",
                "MessageAttributes": {
                    "traceparent": {"DataType": "String", "StringValue": "00-abc"}
                },
            }
        ]
    )
    redriver = SQSDlqRedriver(
        "https://sqs/source",
        "https://sqs/dlq",
        "us-east-1",
        session=_FakeSession(client),
    )

    count = await redriver.redrive(max_messages=10)

    assert count == 1
    assert client.sent[0]["QueueUrl"] == "https://sqs/source"
    assert client.sent[0]["MessageBody"] == '{"booking_id": "BK-1"}'
    assert "MessageAttributes" in client.sent[0]  # trace context preserved
    assert client.deleted[0]["QueueUrl"] == "https://sqs/dlq"
    assert client.deleted[0]["ReceiptHandle"] == "rh-1"


async def test_redrive_links_replay_and_propagates_replayed_from(spans):
    from pymidil.event.otel import current_trace_ids, get_tracer, inject_headers

    # an original flow's trace context
    original_carrier: dict = {}
    with get_tracer().start_as_current_span("original"):
        inject_headers(original_carrier)
        original_trace, _ = current_trace_ids()

    client = _FakeSqsClient(
        [
            {
                "Body": '{"booking_id": "BK-1"}',
                "ReceiptHandle": "rh-1",
                "MessageAttributes": {
                    "traceparent": {
                        "DataType": "String",
                        "StringValue": original_carrier["traceparent"],
                    }
                },
            }
        ]
    )
    redriver = SQSDlqRedriver(
        "https://sqs/source",
        "https://sqs/dlq",
        "us-east-1",
        session=_FakeSession(client),
    )
    spans.clear()

    assert await redriver.redrive() == 1

    sent_attrs = client.sent[0]["MessageAttributes"]
    new_trace = sent_attrs["traceparent"]["StringValue"].split("-")[1]
    assert new_trace != original_trace  # replay runs in its own trace
    assert (
        sent_attrs["replayed_from"]["StringValue"] == original_trace
    )  # marker propagated

    replay = next(s for s in spans.get_finished_spans() if s.name.startswith("replay "))
    assert replay.attributes["replayed_from.trace_id"] == original_trace
    assert any(
        link.context.trace_id == int(original_trace, 16) for link in replay.links
    )


async def test_emitter_surfaces_replayed_from():
    from pymidil.event.otel import get_tracer

    sink = ListSink()
    hook = TelemetryDispatchHook(sink, source_service="payment-svc")
    msg = Message(
        id="EVT-2",
        body={},
        metadata={"event_type": "PaymentRequested", "replayed_from": "abc123"},
    )
    with get_tracer().start_as_current_span("process"):
        await hook.on_complete(msg, "sqs", duration_ms=1.0)

    assert sink.events[0].replayed_from == "abc123"
