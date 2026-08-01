"""The producer-side event contract.

Two guarantees, kept in one place:
  1. ``publish(event)`` hands the transport the typed ``Event`` (no flattening
     at the seam — the transport frames it for its own wire).
  2. :func:`event_to_wire` maps that ``Event`` onto the canonical CloudEvents
     wire attributes (binary content mode: ``data`` is the body, identity rides
     the side-channel), so a consumer reconstructs the same event.
"""

from __future__ import annotations

import pytest

from pymidil.event.core import Event
from pymidil.event.producer.base import BaseProducerConfig, EventProducer
from pymidil.event.wire import (
    EVENT_ID_FIELD,
    EVENT_SOURCE_FIELD,
    EVENT_SUBJECT_FIELD,
    EVENT_TIME_FIELD,
    EVENT_TYPE_FIELD,
    EXT_PREFIX,
    IDEMPOTENCY_KEY_FIELD,
    event_to_wire,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"  # dispatch uses asyncio primitives; trio is out of scope


class RecordingProducer(EventProducer):
    def __init__(self) -> None:
        super().__init__(BaseProducerConfig(type="fake"))
        self.event = None

    async def _publish(self, event) -> None:
        self.event = event

    async def close(self) -> None:
        ...


# ---- publish forwards the typed Event to the transport ------------------------


async def test_publish_hands_the_transport_the_typed_event():
    producer = RecordingProducer()
    event = Event(id="evt-1", source="checkout", type="order.placed", data={"order": 1})
    await producer.publish(event)
    assert producer.event is event  # no flattening at the seam


# ---- event_to_wire: the canonical CloudEvents wire mapping ---------------------


def test_event_data_is_the_body_attributes_ride_the_side_channel():
    wire = event_to_wire(
        Event(
            id="evt-1",
            source="checkout",
            type="order.placed",
            subject="order-1",
            data={"order": 1},
            idempotency_key="order-1",
        )
    )
    assert wire[EVENT_ID_FIELD] == "evt-1"
    assert wire[EVENT_SOURCE_FIELD] == "checkout"
    assert wire[EVENT_TYPE_FIELD] == "order.placed"
    assert wire[EVENT_SUBJECT_FIELD] == "order-1"
    assert wire[IDEMPOTENCY_KEY_FIELD] == "order-1"
    assert EVENT_TIME_FIELD in wire  # always stamped


def test_optional_attributes_are_omitted_when_unset():
    wire = event_to_wire(Event(id="evt-2", source="svc", type="thing.happened"))
    assert EVENT_SUBJECT_FIELD not in wire
    assert IDEMPOTENCY_KEY_FIELD not in wire


def test_extensions_ride_with_the_ext_prefix():
    wire = event_to_wire(
        Event(id="e", source="s", type="t", extensions={"tenant": "acme"})
    )
    assert wire[f"{EXT_PREFIX}tenant"] == "acme"
