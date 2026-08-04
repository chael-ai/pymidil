"""Sync helpers for observing publish/consume outside pymidil's event bus.

Intended for Django, Celery, Django-Q, and other sync runtimes that already
own their enqueue / handler path and only need Midil telemetry around it.

Important: ``send`` / ``handle`` run in a normal sync context (no event loop),
so Django ORM and other sync-only APIs are safe. Only telemetry emission is
bridged through asyncio.
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

    # Prefer an explicit message_id (e.g. business event_id) for lineage so
    # producer/consumer envelopes group together. Fall back to send()'s return
    # value (transport id) only when message_id was not provided.
    delivery_id = message_id or str(uuid.uuid4())

    # Sync ``with`` keeps send() outside any event loop (Django ORM safe).
    # Observation.__exit__ emits telemetry via run_sync after closing the span.
    with publish(
        event_type,
        destination=destination,
        payload=payload,
        idempotency_key=idempotency_key,
        headers=headers,
    ) as pub:
        result = send()
        if message_id is not None:
            pub.sent(message_id)
        else:
            pub.sent(result if result is not None else delivery_id)
        return result


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

    # Sync ``with`` keeps handle() outside any event loop (Django ORM safe).
    with observe(
        message_id,
        event_type,
        payload=payload,
        idempotency_key=idempotency_key,
        headers=headers,
    ):
        handle()
