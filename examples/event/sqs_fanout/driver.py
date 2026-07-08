"""The ingress — a stand-in checkout gateway that emits ``OrderPaid`` events.

Every fan-out trace starts here, from a single origin. This is also the smallest
complete example of the producer side of pymidil: an :class:`SQSProducer` plus a
:class:`TelemetryProducerHook` so each publish shows up as the trace's first step.
"""

from __future__ import annotations

import asyncio
import uuid

from loguru import logger

from pymidil.event import SQSProducer, SQSProducerEventConfig

from .services import producer_telemetry
from .settings import INGRESS_SERVICE, Settings


class OrderDriver:
    """Emits ``OrderPaid`` at a steady rate until asked to stop."""

    def __init__(self, s: Settings, session, source_url: str) -> None:
        self._settings = s
        self._producer = SQSProducer(
            SQSProducerEventConfig(
                type="sqs",
                queue_url=source_url,
                endpoint_url=s.endpoint_url,
                aws_region=s.region,
            ),
            session=session,
        )
        self._producer.add_hook(producer_telemetry(s, INGRESS_SERVICE))

    async def run(self, stop: asyncio.Event) -> None:
        interval = 1.0 / self._settings.orders_per_sec
        emitted = 0
        while not stop.is_set():
            order = f"OD-{uuid.uuid4().hex[:6].upper()}"
            await self._producer.publish(
                {"order_id": order, "event_type": "OrderPaid"},
                metadata={
                    "event_type": "OrderPaid",
                    "idempotency_key": f"{order}:OrderPaid",
                },
            )
            emitted += 1
            if emitted % 10 == 0:
                logger.info("driver: emitted {} orders", emitted)
            # Sleep between orders, but wake immediately on shutdown.
            try:
                await asyncio.wait_for(stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
