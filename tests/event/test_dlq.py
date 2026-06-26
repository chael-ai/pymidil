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
