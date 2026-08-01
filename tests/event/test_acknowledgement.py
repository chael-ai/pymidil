"""Disposition routing: dispatch resolves an outcome and settles the Delivery.

The ``Acknowledger`` abstraction is gone — settlement (ack / retry / dlq) now
lives on the :class:`~pymidil.event.core.Delivery` (the transport attempt owns
how it is settled). These pin the successor behaviors:

- ``NoAckDelivery`` dispositions are safe no-ops (was: consumer-as-acknowledger
  no-op defaults);
- ``SqsDelivery`` implements the three dispositions against the SQS wire (was:
  SQS-as-acknowledger dispositions);
- dispatch maps a subscriber outcome onto ``delivery.ack/retry/dlq`` (was:
  dispatch → disposition on the acknowledger), verified with a recording
  Delivery.
"""

from __future__ import annotations

from typing import Optional

import pytest

from pymidil.event.consumer.sqs import (
    SQSConsumer,
    SQSConsumerEventConfig,
    SqsDelivery,
)
from pymidil.event.consumer.strategies.base import (
    BaseConsumerConfig,
    EventConsumer,
)
from pymidil.event.core import Event, NoAckDelivery
from pymidil.event.exceptions import RetryableEventError
from pymidil.event.subscriber.base import EventSubscriber, FunctionSubscriber
from pymidil.utils.backoff import ExponentialBackoff

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


def _event(**over) -> Event:
    base = dict(id="EVT-1", source="orders-svc", type="order.created", data={"v": 1})
    base.update(over)
    return Event(**base)


# --- NoAckDelivery: the three dispositions are safe no-ops ---
async def test_noack_delivery_dispositions_are_noops():
    # no broker settlement -> each disposition returns without effect
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


# --- SqsDelivery implements the three dispositions against the SQS wire ---
SOURCE = "arn:aws:sqs:us-east-1:123456789012:source"
DLQ = "arn:aws:sqs:us-east-1:123456789012:dlq"


class _FakeSqsClient:
    def __init__(self) -> None:
        self.deleted: list = []
        self.visibility: list = []
        self.sent: list = []

    async def delete_message(self, **kw):
        self.deleted.append(kw)

    async def change_message_visibility(self, **kw):
        self.visibility.append(kw)

    async def send_message(self, **kw):
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


def _sqs_delivery(client, *, dlq=DLQ) -> SqsDelivery:
    config = SQSConsumerEventConfig(queue_url=SOURCE, dlq_url=dlq)
    return SqsDelivery(
        _event(),
        session=_FakeSession(client),
        config=config,
        backoff=ExponentialBackoff(base_delay=5, max_delay=300),
        message_id="EVT-1",
        receipt_handle="rh-1",
        raw_attributes={"ApproximateReceiveCount": "3"},
    )


async def test_sqs_ack_deletes_from_source():
    client = _FakeSqsClient()
    await _sqs_delivery(client).ack()
    assert client.deleted[0]["ReceiptHandle"] == "rh-1"
    assert client.deleted[0]["QueueUrl"] == SOURCE


async def test_sqs_retry_resets_visibility():
    client = _FakeSqsClient()
    await _sqs_delivery(client).retry()
    assert client.visibility[0]["ReceiptHandle"] == "rh-1"
    assert not client.deleted and not client.sent


async def test_sqs_dlq_sends_then_deletes():
    client = _FakeSqsClient()
    await _sqs_delivery(client).dlq()
    assert client.sent[0]["QueueUrl"] == DLQ
    assert client.deleted[0]["QueueUrl"] == SOURCE


async def test_sqs_dlq_without_dlq_falls_back_to_retry():
    client = _FakeSqsClient()
    await _sqs_delivery(client, dlq=None).dlq()
    assert client.visibility and not client.sent


# --- SQSConsumer still wires an SqsDelivery from the raw wire ---
def test_sqs_consumer_constructs():
    consumer = SQSConsumer(
        SQSConsumerEventConfig(queue_url=SOURCE, dlq_url=DLQ),
        session=_FakeSession(_FakeSqsClient()),
    )
    assert isinstance(consumer, EventConsumer)


# --- dispatch maps outcome -> disposition on the delivery ---
class _RecordingDelivery(NoAckDelivery):
    """A recording Delivery double: captures which disposition dispatch calls."""

    def __init__(self, event: Event) -> None:
        super().__init__(event)
        self.calls: list = []

    async def _ack(self) -> None:
        self.calls.append("ack")

    async def _retry(self) -> None:
        self.calls.append("retry")

    async def _dlq(self, error: Optional[Exception] = None) -> None:
        self.calls.append("dlq")


async def _dispatch_with(subscriber) -> _RecordingDelivery:
    consumer = _MemConsumer(_Cfg())
    consumer.subscribe(subscriber)
    delivery = _RecordingDelivery(_event())
    await consumer.dispatch(delivery)
    return delivery


async def test_success_outcome_acks():
    async def handler(event):
        return None

    delivery = await _dispatch_with(FunctionSubscriber(handler=handler))
    assert delivery.calls == ["ack"]


async def test_retryable_outcome_retries():
    class Retrying(EventSubscriber):
        async def handle(self, event) -> None:
            raise RetryableEventError("transient")

    delivery = await _dispatch_with(Retrying())
    assert delivery.calls == ["retry"]


async def test_failure_outcome_dead_letters():
    class Failing(EventSubscriber):
        async def handle(self, event) -> None:
            raise ValueError("boom")

    delivery = await _dispatch_with(Failing())
    assert delivery.calls == ["dlq"]
