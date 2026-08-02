"""Settlement routing: dispatch resolves an outcome and settles the Delivery.

Pins the merged architecture:

- ``NoAckDelivery`` dispositions are safe no-ops (push transports);
- ``SQSSettlement`` performs the physical SQS calls; ``SQSDelivery`` reads the
  wire and delegates writes to it;
- an SQS consumer must DECLARE its terminal fate (``dlq_url`` XOR ``no_dlq``) —
  the silent no-DLQ fallback is gone;
- dispatch maps outcomes onto the delivery, routing terminal failures by the
  declared fate, and bounds retries by the consumer's RetryConfig budget.
"""

from __future__ import annotations

from typing import Literal

import pytest
from pydantic import Field, ValidationError

from pymidil.transports.sqs.consumer import (
    SQSConsumer,
    SQSConsumerEventConfig,
    SQSDelivery,
    SQSSettlement,
)
from pymidil.event.consumer.strategies.base import (
    BaseConsumerConfig,
    EventConsumer,
)
from pymidil.event.core import Delivery, Event, NoAckDelivery, Settlement
from pymidil.event.exceptions import RetryableEventError
from pymidil.event.retry import RetryConfig
from pymidil.event.subscriber.base import EventSubscriber, FunctionSubscriber

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"  # dispatch() is asyncio-native


class _Cfg(BaseConsumerConfig):
    type: str = "memory"


class _MemConsumer(EventConsumer):
    async def start(self) -> None:
        ...

    async def stop(self) -> None:
        ...

    @property
    def capabilities(self):
        from pymidil.event.retry import TransportCapabilities

        return TransportCapabilities(counts_attempts=True)


def _event(**over) -> Event:
    base = dict(id="EVT-1", source="orders-svc", type="order.created", data={"v": 1})
    base.update(over)
    return Event(**base)


# --- NoAckDelivery: the three dispositions are safe no-ops ---
async def test_noack_delivery_dispositions_are_noops():
    # (fresh delivery per disposition: a delivery settles exactly once)
    assert await NoAckDelivery(_event()).ack() is None
    assert await NoAckDelivery(_event()).retry() is None
    assert await NoAckDelivery(_event()).dlq(RuntimeError("x")) is None


async def test_noack_delivery_still_latches():
    delivery = NoAckDelivery(_event())
    await delivery.ack()
    assert delivery.settled and delivery.disposition == "ack"
    await delivery.retry()  # refused: already settled
    assert delivery.disposition == "ack"


# --- the config must DECLARE a terminal fate ---
SOURCE = "arn:aws:sqs:us-east-1:123456789012:source"
DLQ = "arn:aws:sqs:us-east-1:123456789012:dlq"


def test_config_refuses_undeclared_terminal_fate():
    with pytest.raises(ValidationError, match="declared fate"):
        SQSConsumerEventConfig(queue_url=SOURCE)


def test_config_refuses_ambiguous_terminal_fate():
    with pytest.raises(ValidationError, match="mutually exclusive"):
        SQSConsumerEventConfig(queue_url=SOURCE, dlq_url=DLQ, no_dlq="requeue")


def test_config_refuses_requeue_with_finite_budget():
    with pytest.raises(ValidationError, match="terminate nothing"):
        SQSConsumerEventConfig(queue_url=SOURCE, no_dlq="requeue")  # default budget=5


def test_config_terminal_action_reflects_declaration():
    assert (
        SQSConsumerEventConfig(queue_url=SOURCE, dlq_url=DLQ).terminal_action == "dlq"
    )
    assert (
        SQSConsumerEventConfig(
            queue_url=SOURCE, no_dlq="requeue", retry=RetryConfig(max_attempts=None)
        ).terminal_action
        == "requeue"
    )
    assert (
        SQSConsumerEventConfig(queue_url=SOURCE, no_dlq="drop").terminal_action
        == "drop"
    )


# --- SQSSettlement performs the physical dispositions against the SQS wire ---
class _FakeSqsClient:
    def __init__(self, *, fail_send: bool = False) -> None:
        self.deleted: list = []
        self.visibility: list = []
        self.sent: list = []
        self._fail_send = fail_send

    async def delete_message(self, **kw):
        self.deleted.append(kw)

    async def change_message_visibility(self, **kw):
        self.visibility.append(kw)

    async def send_message(self, **kw):
        if self._fail_send:
            from botocore.exceptions import ClientError

            raise ClientError({"Error": {"Code": "OOPS"}}, "SendMessage")
        self.sent.append(kw)


class _FakeCtx:
    def __init__(self, client):
        self._client = client

    async def __aenter__(self):
        return self._client

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, client):
        self._client = client

    def client(self, *_a, **_kw):
        return _FakeCtx(self._client)


def _settlement(client, *, dlq=DLQ) -> SQSSettlement:
    config = SQSConsumerEventConfig(
        queue_url=SOURCE,
        dlq_url=dlq,
        no_dlq=None if dlq else "requeue",
        retry=RetryConfig() if dlq else RetryConfig(max_attempts=None),
    )
    return SQSSettlement(
        session=_FakeSession(client),
        config=config,
        message_id="MID-1",
        receipt_handle="rh-1",
        raw_attributes={"ApproximateReceiveCount": "3"},
    )


async def test_sqs_ack_deletes_from_source():
    client = _FakeSqsClient()
    await _settlement(client).ack()
    assert client.deleted[0]["ReceiptHandle"] == "rh-1"
    assert client.deleted[0]["QueueUrl"] == SOURCE


async def test_sqs_retry_enacts_policy_delay():
    client = _FakeSqsClient()
    await _settlement(client).retry(42.7)
    assert client.visibility[0]["VisibilityTimeout"] == 43
    assert not client.deleted and not client.sent


async def test_sqs_dlq_sends_body_and_carrier_then_deletes():
    client = _FakeSqsClient()
    await _settlement(client).dlq(_event(), {"traceparent": "00-abc"}, ValueError("x"))
    assert client.sent[0]["QueueUrl"] == DLQ
    assert '"v": 1' in client.sent[0]["MessageBody"]  # event.data, not the model
    attrs = client.sent[0]["MessageAttributes"]
    assert attrs["traceparent"]["StringValue"] == "00-abc"
    assert client.deleted[0]["QueueUrl"] == SOURCE  # removed only after divert


async def test_sqs_dlq_divert_failure_keeps_message_on_source():
    client = _FakeSqsClient(fail_send=True)
    await _settlement(client).dlq(_event(), {}, ValueError("x"))
    assert not client.deleted  # never delete a message we failed to divert


# --- SQSDelivery: reads the wire, delegates writes, declares its fate ---
def _delivery(client, *, dlq=DLQ, no_dlq=None, receive_count="3") -> SQSDelivery:
    config = SQSConsumerEventConfig(
        queue_url=SOURCE,
        dlq_url=dlq,
        no_dlq=no_dlq,
        retry=RetryConfig(max_attempts=None) if no_dlq == "requeue" else RetryConfig(),
    )
    settlement = SQSSettlement(
        session=_FakeSession(client),
        config=config,
        message_id="MID-1",
        receipt_handle="rh-1",
        raw_attributes={"ApproximateReceiveCount": receive_count},
    )
    return SQSDelivery(
        _event(),
        settlement=settlement,
        message_id="MID-1",
        system_attributes={"ApproximateReceiveCount": receive_count},
        wire_attributes={
            "traceparent": {"StringValue": "00-abc", "DataType": "String"},
        },
    )


async def test_delivery_reads_wire_and_delegates():
    client = _FakeSqsClient()
    d = _delivery(client)
    assert d.retry_count == 3
    assert d.transport_id == "MID-1"
    assert d.terminal_action == "dlq"
    assert d.carrier()["traceparent"] == "00-abc"
    await d.dlq(ValueError("x"))
    assert client.sent and client.deleted  # divert + remove, via the settlement


async def test_delivery_declares_requeue_fate():
    d = _delivery(_FakeSqsClient(), dlq=None, no_dlq="requeue")
    assert d.terminal_action == "requeue"


def test_sqs_consumer_constructs():
    consumer = SQSConsumer(
        SQSConsumerEventConfig(queue_url=SOURCE, dlq_url=DLQ),
        session=_FakeSession(_FakeSqsClient()),
    )
    assert isinstance(consumer, EventConsumer)
    assert consumer.capabilities.counts_attempts


# --- dispatch maps outcome -> disposition, routed by the declared fate ---
class _RecordingSettlement(Settlement):
    """Records every physical write, with a declarable fate — composition,
    exactly how a real transport plugs in."""

    def __init__(self, fate: Literal["dlq", "requeue", "drop"] = "dlq") -> None:
        self.calls: list = []
        self._fate = fate

    @property
    def terminal_action(self):
        return self._fate

    async def ack(self) -> None:
        self.calls.append("ack")

    async def retry(self, delay: float) -> None:
        self.calls.append(f"retry(delay={delay:.0f})")

    async def dlq(self, event, carrier, error=None) -> None:
        self.calls.append("dlq")


class _RecordingDelivery(Delivery):
    """A Delivery double: reads overridden (attempt), writes recorded via the
    composed settlement."""

    def __init__(
        self,
        event: Event,
        *,
        fate: Literal["dlq", "requeue", "drop"] = "dlq",
        attempt: int = 1,
    ) -> None:
        super().__init__(event, _RecordingSettlement(fate))
        self._attempt = attempt

    @property
    def calls(self) -> list:
        return self._settlement.calls  # type: ignore[attr-defined]

    @property
    def retry_count(self) -> int:
        return self._attempt


class _RetryCfg(BaseConsumerConfig):
    """A mem config carrying a retry policy, like a pull transport's would."""

    type: str = "memory"
    retry: RetryConfig = Field(
        default_factory=lambda: RetryConfig(
            max_attempts=3, backoff_base_delay=2, backoff_max_delay=60, jitter=False
        )
    )


async def _dispatch_with(subscriber, delivery, *, config=None) -> None:
    consumer = _MemConsumer(config or _Cfg())
    consumer.subscribe(subscriber)
    await consumer.dispatch(delivery)


class _Retrying(EventSubscriber):
    async def handle(self, event) -> None:
        raise RetryableEventError("transient")


class _Failing(EventSubscriber):
    async def handle(self, event) -> None:
        raise ValueError("boom")


async def test_success_outcome_acks():
    async def handler(event):
        return None

    d = _RecordingDelivery(_event())
    await _dispatch_with(FunctionSubscriber(handler=handler), d)
    assert d.calls == ["ack"]


async def test_retryable_outcome_retries_with_policy_delay():
    d = _RecordingDelivery(_event(), attempt=2)
    await _dispatch_with(_Retrying(), d, config=_RetryCfg())
    # attempt 2 on a base-2 no-jitter curve -> 2 * 2^(2-1) = 4s
    assert d.calls == ["retry(delay=4)"]


async def test_failure_routes_to_declared_dlq_fate():
    d = _RecordingDelivery(_event(), fate="dlq")
    await _dispatch_with(_Failing(), d)
    assert d.calls == ["dlq"]


async def test_failure_routes_to_declared_requeue_fate():
    d = _RecordingDelivery(_event(), fate="requeue")
    await _dispatch_with(_Failing(), d)
    assert len(d.calls) == 1 and d.calls[0].startswith("retry")


async def test_failure_routes_to_declared_drop_fate():
    d = _RecordingDelivery(_event(), fate="drop")
    await _dispatch_with(_Failing(), d)
    assert d.calls == ["ack"]


# --- the retry budget: exhausted retryables become terminal ---
async def test_retry_budget_exhaustion_becomes_terminal():
    d = _RecordingDelivery(_event(), fate="dlq", attempt=3)  # budget: max_attempts=3
    await _dispatch_with(_Retrying(), d, config=_RetryCfg())
    assert d.calls == ["dlq"]


async def test_within_budget_still_retries():
    d = _RecordingDelivery(_event(), fate="dlq", attempt=2)
    await _dispatch_with(_Retrying(), d, config=_RetryCfg())
    assert d.calls[0].startswith("retry")


async def test_unbounded_budget_never_exhausts():
    class _Unbounded(BaseConsumerConfig):
        type: str = "memory"
        retry: RetryConfig = Field(
            default_factory=lambda: RetryConfig(max_attempts=None, jitter=False)
        )

    d = _RecordingDelivery(_event(), fate="dlq", attempt=9999)
    await _dispatch_with(_Retrying(), d, config=_Unbounded())
    assert d.calls[0].startswith("retry")
