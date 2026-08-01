"""The re-architected core model — Event (fact) + Delivery (attempt) + Context.

Phase 1a: these types exist standalone and behave; nothing else is wired to
them yet. The properties under test are the load-bearing design decisions:
event.id as logical identity, dedup defaulting to it, the delivery holding the
disposition, and the context as a pure verb facade over the delivery.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pytest

from pymidil.event.core import Event, Delivery

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class FakeDelivery(Delivery):
    """A test double transport — records dispositions, no broker."""

    def __init__(self, event: Event, *, receive_count: int = 1) -> None:
        super().__init__(event)
        self._receive_count = receive_count
        self.acked = self.retried = False
        self.dead_lettered: Optional[BaseException] = None

    @property
    def retry_count(self) -> int:
        return self._receive_count

    async def _ack(self) -> None:
        self.acked = True

    async def _retry(self) -> None:
        self.retried = True

    async def _dlq(self, error: Optional[Exception] = None) -> None:
        self.dead_lettered = error or RuntimeError("no error given")


def _event(**over) -> Event:
    base = dict(id="evt-1", source="orders-svc", type="order.created", data={"n": 1})
    base.update(over)
    return Event(**base)


# ---- Event: the immutable fact ------------------------------------------------


def test_event_is_cloudevents_shaped():
    e = _event(subject="OD-99")
    assert (e.id, e.source, e.type, e.subject) == (
        "evt-1",
        "orders-svc",
        "order.created",
        "OD-99",
    )
    assert e.data == {"n": 1}
    assert e.datacontenttype == "application/json"
    assert isinstance(e.time, datetime)


def test_dedup_key_defaults_to_id():
    # event.id IS the logical identity — no separate key needed for the common case
    assert _event().dedup_key == "evt-1"


def test_dedup_key_honors_override():
    assert _event(idempotency_key="order-1:charge").dedup_key == "order-1:charge"


def test_event_carries_no_transport_concept():
    fields = set(Event.model_fields)
    for leaked in (
        "metadata",
        "headers",
        "ack_handle",
        "receipt_handle",
        "partition",
        "offset",
    ):
        assert (
            leaked not in fields
        ), f"{leaked} is a transport concern, not an event field"


def test_event_is_serializable():
    e = _event(time=datetime(2026, 1, 1, tzinfo=timezone.utc))
    dumped = e.model_dump(mode="json")
    assert dumped["id"] == "evt-1" and dumped["type"] == "order.created"
    assert Event.model_validate(dumped).id == "evt-1"


# ---- Delivery: the transport attempt -----------------------------------------


async def test_delivery_holds_the_disposition():
    d = FakeDelivery(_event(), receive_count=3)
    assert d.event.id == "evt-1"
    assert d.retry_count == 3
    await d.ack()
    assert d.acked


async def test_base_carrier_is_empty():
    assert FakeDelivery(_event()).carrier() == {}


# ---- Delivery latch: one delivery settles exactly once ------------------------


async def test_first_disposition_wins():
    d = FakeDelivery(_event())
    await d.dlq(ValueError("bad"))
    assert d.settled and d.disposition == "dlq"
    await d.ack()  # refused: already settled (logged, no-op)
    assert not d.acked
    assert d.disposition == "dlq"


async def test_double_settlement_is_refused_not_applied():
    d = FakeDelivery(_event())
    await d.ack()
    assert d.acked and d.disposition == "ack"
    await d.retry()
    assert not d.retried  # the physical retry never ran
    await d.dlq(RuntimeError("late"))
    assert d.dead_lettered is None


async def test_unsettled_delivery_reports_no_disposition():
    d = FakeDelivery(_event())
    assert d.settled is False
    assert d.disposition is None
