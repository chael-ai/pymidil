"""Producers inject the active OTel trace into the wire carrier."""

import pytest

from pymidil.event.otel import current_trace_ids, get_tracer
from pymidil.event.producer.sqs import (
    SQSProducer,
    SQSProducerEventConfig,
    build_sqs_message_attributes,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


SOURCE = "arn:aws:sqs:us-east-1:123456789012:orders"


def test_build_sqs_message_attributes_filters_non_scalars():
    headers = {
        "traceparent": "00-abc",
        "count": 3,
        "flag": True,
        "obj": {"a": 1},
        "none": None,
    }
    attributes = build_sqs_message_attributes(headers)
    assert attributes["traceparent"] == {"DataType": "String", "StringValue": "00-abc"}
    assert attributes["count"]["StringValue"] == "3"
    assert "obj" not in attributes
    assert "none" not in attributes


class _FakeSqsClient:
    def __init__(self) -> None:
        self.sent: list = []

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


async def test_sqs_producer_injects_active_trace_into_attributes():
    client = _FakeSqsClient()
    producer = SQSProducer(
        SQSProducerEventConfig(queue_url=SOURCE), session=_FakeSession(client)
    )

    with get_tracer().start_as_current_span("publisher"):
        trace_id, _ = current_trace_ids()
        await producer.publish({"x": 1})

    attrs = client.sent[0]["MessageAttributes"]
    assert "traceparent" in attrs
    # the injected traceparent carries the active trace id
    assert trace_id in attrs["traceparent"]["StringValue"]
