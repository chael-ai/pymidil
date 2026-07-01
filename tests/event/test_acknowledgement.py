"""Acknowledger: consumer-as-acknowledger, SQS dispositions, dispatch wiring."""

import pytest

from pymidil.event.acknowledgement import Acknowledger
from pymidil.event.consumer.sqs import SQSConsumer, SQSConsumerEventConfig
from pymidil.event.consumer.strategies.base import (
    BaseConsumerConfig,
    ConsumerMessage,
    EventConsumer,
)
from pymidil.event.exceptions import RetryableEventError
from pymidil.event.message import Message
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


# --- consumer IS an Acknowledger, with no-op defaults ---
async def test_consumer_is_acknowledger_with_noop_defaults():
    consumer = _MemConsumer(_Cfg())
    assert isinstance(consumer, Acknowledger)
    # no overrides -> all three dispositions are safe no-ops
    await consumer.ack(Message(id="1", body={}))
    await consumer.retry(Message(id="1", body={}))
    await consumer.dlq(Message(id="1", body={}), error=RuntimeError("x"))


# --- SQS implements the three dispositions ---
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


def _cmsg() -> ConsumerMessage:
    return ConsumerMessage(
        id="EVT-1",
        body={"v": 1},
        ack_handle="rh-1",
        metadata={"ApproximateReceiveCount": "3"},
    )


def _sqs(client, *, dlq=DLQ) -> SQSConsumer:
    return SQSConsumer(
        SQSConsumerEventConfig(queue_url=SOURCE, dlq_url=dlq),
        session=_FakeSession(client),
    )


async def test_sqs_ack_deletes_from_source():
    client = _FakeSqsClient()
    await _sqs(client).ack(_cmsg())
    assert client.deleted[0]["ReceiptHandle"] == "rh-1"
    assert client.deleted[0]["QueueUrl"] == SOURCE


async def test_sqs_retry_resets_visibility():
    client = _FakeSqsClient()
    await _sqs(client).retry(_cmsg())
    assert client.visibility[0]["ReceiptHandle"] == "rh-1"
    assert not client.deleted and not client.sent


async def test_sqs_dlq_sends_then_deletes():
    client = _FakeSqsClient()
    await _sqs(client).dlq(_cmsg())
    assert client.sent[0]["QueueUrl"] == DLQ
    assert client.deleted[0]["QueueUrl"] == SOURCE


async def test_sqs_dlq_without_dlq_falls_back_to_retry():
    client = _FakeSqsClient()
    await _sqs(client, dlq=None).dlq(_cmsg())
    assert client.visibility and not client.sent


# --- dispatch maps outcome -> disposition on the acknowledger ---
class _RecordingAck(Acknowledger):
    def __init__(self) -> None:
        self.calls: list = []

    async def ack(self, message) -> None:
        self.calls.append("ack")

    async def retry(self, message) -> None:
        self.calls.append("retry")

    async def dlq(self, message, error=None) -> None:
        self.calls.append("dlq")


async def _dispatch_with(subscriber) -> _RecordingAck:
    consumer = _MemConsumer(_Cfg())
    rec = _RecordingAck()
    consumer.use_acknowledger(rec)
    consumer.subscribe(subscriber)
    await consumer.dispatch(Message(id="1", body={}))
    return rec


async def test_success_outcome_acks():
    async def handler(event):
        return None

    rec = await _dispatch_with(FunctionSubscriber(handler=handler))
    assert rec.calls == ["ack"]


async def test_retryable_outcome_retries():
    class Retrying(EventSubscriber):
        async def handle(self, event) -> None:
            ...

        async def __call__(self, event):
            raise RetryableEventError("transient")

    rec = await _dispatch_with(Retrying())
    assert rec.calls == ["retry"]


async def test_failure_outcome_dead_letters():
    class Failing(EventSubscriber):
        async def handle(self, event) -> None:
            ...

        async def __call__(self, event):
            raise ValueError("boom")

    rec = await _dispatch_with(Failing())
    assert rec.calls == ["dlq"]
