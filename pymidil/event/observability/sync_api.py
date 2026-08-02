"""Sync helpers for observing publish/consume outside pymidil's event bus.

Intended for Django, Celery, Django-Q, and other sync runtimes that already
own their enqueue / handler path and only need Midil telemetry around it.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from functools import lru_cache
from typing import Any, Optional, TypeVar

from pymidil.event.observability.config import (
    TelemetrySettings,
    create_consumer_observer,
    create_producer_observer,
)
from pymidil.event.observability.observer import (
    ConsumerObserver,
    HeadersLike,
    ProducerObserver,
)
from pymidil.utils.sync import run_sync

T = TypeVar("T")


@lru_cache(maxsize=1)
def _cached_producer_observer() -> ProducerObserver:
    return create_producer_observer()


@lru_cache(maxsize=32)
def _cached_consumer_observer(consumer: str) -> ConsumerObserver:
    return create_consumer_observer(consumer)


def clear_observer_caches() -> None:
    """Drop cached default observers (useful in tests after env changes)."""
    _cached_producer_observer.cache_clear()
    _cached_consumer_observer.cache_clear()


def observe_publish(
    event_type: str,
    *,
    destination: str,
    send: Callable[[], T],
    payload: Any = None,
    idempotency_key: Optional[str] = None,
    headers: HeadersLike = None,
    message_id: Optional[str] = None,
    settings: Optional[TelemetrySettings] = None,
    observer: Optional[ProducerObserver] = None,
) -> T:
    """Observe one sync publish around ``send``.

    When telemetry is disabled (``MIDIL_TELEMETRY_ENABLED=false``), calls
    ``send()`` directly and returns its result.

    Pass ``observer=`` to reuse a pre-built observer, ``settings=`` to build
    from an explicit settings object, or neither to reuse a cached env-backed
    observer.
    """
    resolved = settings or TelemetrySettings()
    if not resolved.enabled:
        return send()

    if observer is not None:
        publish = observer
    elif settings is not None:
        publish = create_producer_observer(settings)
    else:
        publish = _cached_producer_observer()

    fallback_id = message_id or str(uuid.uuid4())

    # Keep the full observation inside one asyncio.run so OTel span
    # enter/exit share a ContextVar context.
    async def _run() -> T:
        async with publish(
            event_type,
            destination=destination,
            payload=payload,
            idempotency_key=idempotency_key,
            headers=headers,
        ) as pub:
            result = send()
            pub.sent(result if result is not None else fallback_id)
            return result

    return run_sync(_run())


def observe_consume(
    message_id: str,
    event_type: str,
    *,
    consumer: str,
    handle: Callable[[], None],
    payload: Any = None,
    idempotency_key: Optional[str] = None,
    headers: HeadersLike = None,
    settings: Optional[TelemetrySettings] = None,
    observer: Optional[ConsumerObserver] = None,
) -> None:
    """Observe one sync handler around ``handle``.

    When telemetry is disabled, calls ``handle()`` directly.
    """
    resolved = settings or TelemetrySettings()
    if not resolved.enabled:
        handle()
        return

    if observer is not None:
        observe = observer
    elif settings is not None:
        observe = create_consumer_observer(consumer, settings)
    else:
        observe = _cached_consumer_observer(consumer)

    async def _run() -> None:
        async with observe(
            message_id,
            event_type,
            payload=payload,
            idempotency_key=idempotency_key,
            headers=headers,
        ):
            handle()

    run_sync(_run())
