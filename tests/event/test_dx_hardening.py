"""DX-hardening guarantees from the blind audit.

- zero-subscriber deliveries are NEVER acked (no silent queue-draining);
- bus.subscribe refuses to guess when multiple consumers are registered;
- the barrels are lazy: importing pymidil / pymidil.event must not require
  the optional transport/CLI dependencies.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from pymidil.event.core import Delivery, Event, Settlement
from pymidil.event.consumer.strategies.base import BaseConsumerConfig, EventConsumer
from pymidil.event.config import EventConfig
from pymidil.event.event_bus import EventBus
from pymidil.exceptions import ConsumerError
from pymidil.event.subscriber.base import FunctionSubscriber

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class _Cfg(BaseConsumerConfig):
    type: str = "memory"


class _MemConsumer(EventConsumer):
    async def start(self) -> None:
        ...

    async def stop(self) -> None:
        ...


class _RecordingSettlement(Settlement):
    def __init__(self) -> None:
        self.calls: list = []

    @property
    def terminal_action(self):
        return "dlq"

    async def ack(self) -> None:
        self.calls.append("ack")

    async def retry(self, delay: float) -> None:
        self.calls.append("retry")

    async def dlq(self, event, carrier, error=None) -> None:
        self.calls.append("dlq")


def _event() -> Event:
    return Event(id="EVT-1", source="svc", type="t", data={})


# ---- zero subscribers: never ack ----------------------------------------------


async def test_zero_subscriber_delivery_is_left_unsettled():
    consumer = _MemConsumer(_Cfg())  # no subscribers on purpose
    settlement = _RecordingSettlement()
    delivery = Delivery(_event(), settlement)
    await consumer.dispatch(delivery)
    assert settlement.calls == []  # nothing physical happened
    assert not delivery.settled  # redelivery-eligible, not deleted


# ---- bus.subscribe: no guessing across consumers -------------------------------


def _bus_with(consumers: dict) -> EventBus:
    bus = EventBus(config=EventConfig())
    for name, consumer in consumers.items():
        bus.include_consumer(name, consumer)
    return bus


async def test_subscribe_defaults_to_the_only_consumer():
    only = _MemConsumer(_Cfg())
    bus = _bus_with({"payments": only})
    bus.subscribe(FunctionSubscriber(handler=lambda e: None))
    assert len(only._subscribers) == 1


async def test_subscribe_refuses_to_guess_between_consumers():
    bus = _bus_with({"a": _MemConsumer(_Cfg()), "b": _MemConsumer(_Cfg())})
    with pytest.raises(ConsumerError, match="pass\\s+subscribe"):
        bus.subscribe(FunctionSubscriber(handler=lambda e: None))


# ---- lazy barrels: base import must not require optional deps ------------------


def test_importing_pymidil_event_is_light():
    """`import pymidil` + `import pymidil.event` must not pull optional deps
    (click/aioboto3/fastapi/redis) — they load lazily on first attribute use."""
    code = (
        "import sys; import pymidil, pymidil.event; "
        "heavy = [m for m in ('click', 'aioboto3', 'fastapi', 'redis') "
        "if m in sys.modules]; "
        "assert not heavy, f'eagerly imported: {heavy}'; print('light')"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "light" in out.stdout


def test_lazy_names_resolve_on_access():
    import pymidil.event as e

    assert e.SQSConsumer.__name__ == "SQSConsumer"
    assert e.EventBus.__name__ == "EventBus"
