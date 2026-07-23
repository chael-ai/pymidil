"""Runtime — start every service, drive ``OrderPaid``, shut down cleanly.

Run from the repo root:

    python -m examples.event.sqs_fanout

Prerequisites:
    LocalStack SQS:  docker run -d -p 127.0.0.1:4566:4566 -e SERVICES=sqs localstack/localstack:3
    Observatory:     uvicorn observatory.asgi:app --port 8080   (in midil-observatory-api)
"""

from __future__ import annotations

import asyncio
import signal

from loguru import logger
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from pymidil.event.otel import configure_tracing

from .driver import OrderDriver
from .infra import create_queues, make_session
from .services import (
    build_branch_producers,
    build_leaf_consumers,
    build_order_consumer,
)
from .settings import SETTINGS, SOURCE_QUEUE


async def main() -> None:
    settings = SETTINGS
    # Tracing is what stitches producer→consumer→producer into one trace id; the
    # in-memory exporter keeps spans local (the Observatory gets telemetry via the
    # hooks, not the OTel exporter).
    configure_tracing(service_name="midil-fanout", exporter=InMemorySpanExporter())

    session = make_session(settings)
    urls = create_queues(settings)

    branch_producers = build_branch_producers(settings, session, urls)
    consumers = [
        build_order_consumer(settings, session, urls, branch_producers),
        *build_leaf_consumers(settings, session, urls),
    ]
    for consumer in consumers:
        await consumer.start()
    logger.info(
        "Fan-out demo live — OrderPaid → {} branches. Telemetry → {}",
        len(branch_producers),
        settings.observatory_url,
    )

    # Stop on Ctrl-C / SIGTERM.
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    driver = OrderDriver(settings, session, urls[SOURCE_QUEUE])
    drive = asyncio.create_task(driver.run(stop))
    await stop.wait()

    logger.info("Shutting down…")
    drive.cancel()
    for consumer in consumers:
        await consumer.stop()


if __name__ == "__main__":
    asyncio.run(main())
