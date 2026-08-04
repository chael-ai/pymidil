"""Sync observation API — Django / Celery style call sites."""

from __future__ import annotations

import pytest

from pymidil.event.observability import (
    EventKind,
    EventStatus,
    TelemetrySettings,
    clear_observer_caches,
    create_consumer_observer,
    create_producer_observer,
    observe_consume,
    observe_publish,
)
from pymidil.event.observability.sinks.base import TelemetrySink


class CapturingSink(TelemetrySink):
    def __init__(self) -> None:
        self.envelopes = []

    async def emit(self, envelope) -> None:
        self.envelopes.append(envelope)


def test_sync_publish_context_manager():
    sink = CapturingSink()
    publish = create_producer_observer(
        TelemetrySettings(
            enabled=True,
            sink="null",
            source_service="checkout-gateway",
            broker="django-q",
            include_payload=True,
        ),
        sink=sink,
    )

    def send():
        return "task-1"

    with publish(
        "OrderPlaced",
        destination="orders",
        payload={"order_id": "OD-1"},
        idempotency_key="OD-1:OrderPlaced",
    ) as pub:
        result = send()
        pub.sent(result)

    assert result == "task-1"
    (env,) = sink.envelopes
    assert env.kind is EventKind.PRODUCER
    assert env.status is EventStatus.SUCCESS
    assert env.message_id == "task-1"
    assert env.broker == "django-q"
    assert env.source_service == "checkout-gateway"


def test_sync_consume_context_manager():
    sink = CapturingSink()
    observe = create_consumer_observer(
        "orders-worker",
        TelemetrySettings(
            enabled=True,
            sink="null",
            source_service="philantify",
            broker="django-q",
        ),
        sink=sink,
    )
    called = []

    with observe(
        "OD-1",
        "OrderPlaced",
        payload={"order_id": "OD-1"},
        idempotency_key="OD-1:OrderPlaced",
    ):
        called.append(True)

    assert called == [True]
    (env,) = sink.envelopes
    assert env.kind is EventKind.CONSUMER
    assert env.status is EventStatus.SUCCESS
    assert env.consumer == "orders-worker"


def test_observe_publish_helper():
    sink = CapturingSink()
    settings = TelemetrySettings(
        enabled=True,
        sink="null",
        source_service="checkout-gateway",
        broker="django-q",
    )
    observer = create_producer_observer(settings, sink=sink)

    result = observe_publish(
        "OrderPlaced",
        destination="orders",
        payload={"order_id": "OD-1"},
        idempotency_key="OD-1:OrderPlaced",
        send=lambda: "task-9",
        observer=observer,
    )

    assert result == "task-9"
    assert sink.envelopes[0].message_id == "task-9"


def test_observe_consume_helper_reraises():
    sink = CapturingSink()
    settings = TelemetrySettings(
        enabled=True,
        sink="null",
        source_service="svc",
        broker="django-q",
    )
    observer = create_consumer_observer("worker", settings, sink=sink)

    with pytest.raises(ValueError, match="boom"):
        observe_consume(
            "m-1",
            "OrderPlaced",
            consumer="worker",
            handle=lambda: (_ for _ in ()).throw(ValueError("boom")),
            observer=observer,
        )

    assert sink.envelopes[0].status is EventStatus.FAILED


def test_helpers_noop_when_disabled():
    clear_observer_caches()
    settings = TelemetrySettings(enabled=False, sink="null")
    called = []

    result = observe_publish(
        "OrderPlaced",
        destination="orders",
        send=lambda: "ok",
        settings=settings,
    )
    observe_consume(
        "m-1",
        "OrderPlaced",
        consumer="worker",
        handle=lambda: called.append(True),
        settings=settings,
    )

    assert result == "ok"
    assert called == [True]


def test_create_observers_from_settings_defaults_broker():
    settings = TelemetrySettings(
        enabled=True,
        sink="null",
        source_service="svc",
        broker=None,
    )
    publish = create_producer_observer(settings)
    observe = create_consumer_observer("worker", settings)
    assert publish._hook._broker == "unknown"
    assert observe._hook._broker == "unknown"


def test_producer_generates_idempotency_key_when_omitted():
    sink = CapturingSink()
    publish = create_producer_observer(
        TelemetrySettings(
            enabled=True,
            sink="null",
            source_service="svc",
            broker="django-q",
        ),
        sink=sink,
    )

    with publish("OrderPlaced", destination="orders") as pub:
        pub.sent("task-1")

    (env,) = sink.envelopes
    assert env.idempotency_key
    assert env.idempotency_key != "task-1"  # generated key, not message id


def test_sync_publish_does_not_raise_otel_context_detach(caplog):
    """Regression: splitting asyncio.run across __enter__/__exit__ broke OTel."""
    import logging

    sink = CapturingSink()
    publish = create_producer_observer(
        TelemetrySettings(
            enabled=True,
            sink="null",
            source_service="checkout-gateway",
            broker="django-q",
        ),
        sink=sink,
    )

    with caplog.at_level(logging.ERROR, logger="opentelemetry.context"):
        with publish("OrderPlaced", destination="orders") as pub:
            pub.sent("task-1")

    assert sink.envelopes
    assert "Failed to detach context" not in caplog.text


def test_observe_publish_prefers_explicit_message_id_over_send_result():
    sink = CapturingSink()
    settings = TelemetrySettings(
        enabled=True,
        sink="null",
        source_service="philantify",
        broker="django-q",
    )
    observer = create_producer_observer(settings, sink=sink)

    result = observe_publish(
        "OrderPlaced",
        destination="orders",
        send=lambda: "django-q-task-id",
        message_id="business-event-id",
        idempotency_key="business-event-id",
        observer=observer,
    )

    assert result == "django-q-task-id"
    (env,) = sink.envelopes
    assert env.message_id == "business-event-id"
    assert env.idempotency_key == "business-event-id"


def test_observe_consume_runs_handle_without_event_loop():
    """Django ORM forbids sync DB work inside asyncio.run — keep handle sync."""
    import asyncio

    sink = CapturingSink()
    settings = TelemetrySettings(
        enabled=True,
        sink="null",
        source_service="philantify",
        broker="django-q",
    )
    observer = create_consumer_observer("worker", settings, sink=sink)
    seen_loop = {"running": None}

    def handle() -> None:
        try:
            asyncio.get_running_loop()
            seen_loop["running"] = True
        except RuntimeError:
            seen_loop["running"] = False

    observe_consume(
        "m-1",
        "OrderPlaced",
        consumer="worker",
        handle=handle,
        observer=observer,
    )

    assert seen_loop["running"] is False
    assert sink.envelopes


def test_sync_publish_keeps_trace_ids_when_loop_already_running():
    """ASGI path: run_sync hops to a worker thread; ContextVars must follow."""
    import asyncio

    sink = CapturingSink()
    publish = create_producer_observer(
        TelemetrySettings(
            enabled=True,
            sink="null",
            source_service="checkout-gateway",
            broker="django-q",
        ),
        sink=sink,
    )

    async def under_loop():
        with publish("OrderPlaced", destination="orders") as pub:
            pub.sent("task-1")

    asyncio.run(under_loop())

    (env,) = sink.envelopes
    assert env.trace_id
    assert env.span_id
