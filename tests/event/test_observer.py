"""Unit tests for ConsumerObserver — no broker, no Observatory, no pymidil consumer.

The observer's promise is that a team's existing loop gets byte-identical
telemetry to a pymidil-managed consumer; these tests pin that behaviour:
outcome classification, trace continuity from transport headers, explicit
marks, failure isolation, and the control-source wiring.
"""

import asyncio
import time

import pytest

from pymidil.event.consumer.strategies.pull import (
    PullEventConsumer,
    PullEventConsumerConfig,
)
from pymidil.event.control import (
    Control,
    ControlState,
    HttpControlSource,
    NullControlSource,
)
from pymidil.event.exceptions import NonRetryableEventError, RetryableEventError
from pymidil.event.observability import (
    ConsumerObserver,
    EventKind,
    EventStatus,
    ProducerObserver,
)
from pymidil.event.observability.sinks.base import TelemetrySink
from pymidil.event.otel import get_tracer

pytestmark = pytest.mark.anyio

TRACEPARENT = "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class CapturingSink(TelemetrySink):
    def __init__(self) -> None:
        self.envelopes = []

    async def emit(self, envelope) -> None:
        self.envelopes.append(envelope)


class ExplodingSink(TelemetrySink):
    async def emit(self, envelope) -> None:
        raise RuntimeError("sink down")


def observer(sink: TelemetrySink, **kw) -> ConsumerObserver:
    return ConsumerObserver(sink=sink, consumer="orders-worker", broker="kafka", **kw)


# ---- outcome → envelope ------------------------------------------------------


async def test_success_envelope_carries_identity_and_timing():
    sink = CapturingSink()
    observe = observer(sink)

    async with observe(
        "orders/0/41",
        "OrderPlaced",
        payload={"order_id": "OD-1"},
        attempts=4,
        idempotency_key="OD-1:OrderPlaced",
    ):
        pass

    (env,) = sink.envelopes
    assert env.status is EventStatus.SUCCESS
    assert env.message_id == "orders/0/41"
    assert env.event_type == "OrderPlaced"
    assert env.broker == "kafka"
    assert env.consumer == "orders-worker"
    assert env.source_service == "orders-worker"
    assert env.attempts == 4
    assert env.idempotency_key == "OD-1:OrderPlaced"
    assert env.payload == {"order_id": "OD-1"}
    assert env.processing_time_ms is not None and env.processing_time_ms >= 0
    # parity with native consumers: routing keys are promoted to top-level
    # envelope fields, never duplicated into the metadata payload
    assert "attempts" not in env.metadata
    assert "event_type" not in env.metadata


async def test_traceparent_in_kafka_style_headers_continues_the_trace():
    sink = CapturingSink()
    observe = observer(sink)

    # aiokafka hands headers over as (str, bytes) tuples
    async with observe(
        "orders/0/42", "OrderPlaced", headers=[("traceparent", TRACEPARENT.encode())]
    ):
        pass

    (env,) = sink.envelopes
    assert env.trace_id == "0af7651916cd43dd8448eb211c80319c"
    assert env.parent_span_id == "b7ad6b7169203331"  # the upstream producer span
    assert env.span_id is not None and env.span_id != env.parent_span_id


async def test_exception_defaults_to_failed_and_propagates():
    sink = CapturingSink()
    observe = observer(sink)

    with pytest.raises(ValueError):
        async with observe("m1", "OrderPlaced"):
            raise ValueError("boom")

    (env,) = sink.envelopes
    assert env.status is EventStatus.FAILED
    assert env.failure_reason == "boom"
    assert env.failure_class == "ValueError"


async def test_pymidil_exceptions_keep_their_semantics():
    sink = CapturingSink()
    observe = observer(sink)

    with pytest.raises(RetryableEventError):
        async with observe("m2", "OrderPlaced"):
            raise RetryableEventError("backend busy")
    with pytest.raises(NonRetryableEventError):
        async with observe("m3", "OrderPlaced"):
            raise NonRetryableEventError("giving up")

    retrying, dlq = sink.envelopes
    assert retrying.status is EventStatus.RETRYING
    assert retrying.failure_reason == "backend busy"
    assert dlq.status is EventStatus.DLQ
    assert dlq.failure_reason == "giving up"


async def test_custom_classifier_wins():
    sink = CapturingSink()
    # Their broker config redelivers on any error → everything is a retry.
    observe = observer(sink, classify=lambda exc: EventStatus.RETRYING)

    with pytest.raises(ValueError):
        async with observe("m4", "OrderPlaced"):
            raise ValueError("transient")

    (env,) = sink.envelopes
    assert env.status is EventStatus.RETRYING


async def test_explicit_mark_overrides_inference():
    sink = CapturingSink()
    observe = observer(sink)

    # The handler resolved the outcome itself (own DLQ topic) — clean exit,
    # but the truthful status is dead-lettered.
    async with observe("m5", "OrderPlaced") as obs:
        try:
            raise RuntimeError("poison message")
        except RuntimeError as exc:
            obs.mark(EventStatus.DLQ, error=exc)

    (env,) = sink.envelopes
    assert env.status is EventStatus.DLQ
    assert env.failure_reason == "poison message"


async def test_mark_duplicate_on_clean_exit():
    sink = CapturingSink()
    observe = observer(sink)

    async with observe("m6", "OrderPlaced") as obs:
        obs.mark(EventStatus.DUPLICATE)

    (env,) = sink.envelopes
    assert env.status is EventStatus.DUPLICATE


async def test_sink_failure_never_reaches_the_consume_loop():
    observe = observer(ExplodingSink())
    async with observe("m7", "OrderPlaced"):
        pass  # no raise — telemetry failure is logged, not propagated


async def test_observation_is_single_use():
    """Reusing an Observation would leak span context and let a stale mark()
    win over the next delivery's outcome — it must refuse loudly."""
    sink = CapturingSink()
    observe = observer(sink)

    obs = observe("m9", "OrderPlaced")
    async with obs:
        pass
    with pytest.raises(RuntimeError, match="single-use"):
        async with obs:
            pass
    assert len(sink.envelopes) == 1  # only the first use emitted


async def test_cancellation_is_not_an_outcome():
    """Shutdown cancellation must not fabricate `failed` envelopes — native
    dispatch emits nothing for in-flight messages at deploy time; parity."""
    sink = CapturingSink()
    observe = observer(sink)

    async def run() -> None:
        async with observe("m8", "OrderPlaced"):
            await asyncio.sleep(10)

    task = asyncio.create_task(run())
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sink.envelopes == []


# ---- construction & control --------------------------------------------------


def test_requires_exactly_one_of_sink_or_url():
    with pytest.raises(ValueError):
        ConsumerObserver(consumer="c", broker="kafka")
    with pytest.raises(ValueError):
        ConsumerObserver(
            consumer="c",
            broker="kafka",
            sink=CapturingSink(),
            observatory_url="http://obs",
        )


def test_control_source_wiring():
    # sink-only → no control plane to poll → null source
    assert isinstance(observer(CapturingSink()).control, NullControlSource)
    # observatory_url → HTTP control source bound to this consumer's identity
    wired = ConsumerObserver(
        observatory_url="http://obs:8080", consumer="orders-worker", broker="kafka"
    )
    assert isinstance(wired.control, HttpControlSource)
    assert "consumers/orders-worker/control" in wired.control._url


# ---- the produce-side twin -----------------------------------------------------


def publisher(sink: TelemetrySink, **kw) -> ProducerObserver:
    return ProducerObserver(
        sink=sink, source_service="checkout-gateway", broker="kafka", **kw
    )


async def test_publish_success_envelope():
    sink = CapturingSink()
    publish = publisher(sink)

    async with publish(
        "OrderPlaced",
        destination="orders",
        payload={"order_id": "OD-1"},
        idempotency_key="OD-1:OrderPlaced",
    ) as pub:
        # routing keys ride the wire headers, like pymidil's own producers
        assert pub.headers["event_type"] == "OrderPlaced"
        assert pub.headers["idempotency_key"] == "OD-1:OrderPlaced"
        pub.sent("orders/0/7")

    (env,) = sink.envelopes
    assert env.kind is EventKind.PRODUCER
    assert env.status is EventStatus.SUCCESS
    assert env.message_id == "orders/0/7"  # groups with the delivery's records
    assert env.event_type == "OrderPlaced"
    assert env.broker == "kafka"
    assert env.source_service == "checkout-gateway"
    assert env.consumer is None
    assert env.payload == {"order_id": "OD-1"}
    assert env.processing_time_ms is not None and env.processing_time_ms >= 0


async def test_publish_propagates_the_enclosing_context_not_the_producer_span():
    """SQS-producer parity: the wire carries the upstream (enclosing) span so
    cross-service lineage stays a clean consumer→consumer chain; the producer
    span itself is what the envelope records."""
    sink = CapturingSink()
    publish = publisher(sink)

    with get_tracer().start_as_current_span("enclosing") as enclosing:
        enclosing_span_id = format(enclosing.get_span_context().span_id, "016x")
        async with publish("OrderPlaced", destination="orders") as pub:
            traceparent = pub.headers["traceparent"]

    # traceparent: 00-<trace_id>-<span_id>-<flags> — the propagated span is the
    # ENCLOSING one, not the producer span the envelope carries.
    carried_span = traceparent.split("-")[2]
    assert carried_span == enclosing_span_id
    (env,) = sink.envelopes
    assert env.span_id is not None and env.span_id != carried_span
    assert env.trace_id == traceparent.split("-")[1]  # same trace, child span


async def test_publish_without_ambient_context_sends_no_traceparent():
    sink = CapturingSink()
    publish = publisher(sink)
    async with publish("OrderPlaced", destination="orders") as pub:
        assert "traceparent" not in pub.headers  # nothing to propagate — honest
    (env,) = sink.envelopes
    assert env.trace_id is not None  # the producer span itself is still recorded


async def test_publish_failure_is_recorded_and_reraised():
    sink = CapturingSink()
    publish = publisher(sink)

    with pytest.raises(ConnectionError):
        async with publish(
            "OrderPlaced", destination="orders", idempotency_key="OD-2:OrderPlaced"
        ):
            raise ConnectionError("broker unreachable")

    (env,) = sink.envelopes
    assert env.kind is EventKind.PRODUCER
    assert env.status is EventStatus.FAILED
    assert env.failure_reason == "broker unreachable"
    # no transport id for a failed send → falls back to the logical key
    assert env.message_id == "OD-2:OrderPlaced"


async def test_publish_cancellation_is_not_an_outcome():
    sink = CapturingSink()
    publish = publisher(sink)

    async def run() -> None:
        async with publish("OrderPlaced", destination="orders"):
            await asyncio.sleep(10)

    task = asyncio.create_task(run())
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sink.envelopes == []


async def test_publish_observation_is_single_use():
    sink = CapturingSink()
    publish = publisher(sink)
    pub = publish("OrderPlaced", destination="orders")
    async with pub:
        pass
    with pytest.raises(RuntimeError, match="single-use"):
        async with pub:
            pass
    assert len(sink.envelopes) == 1


async def test_publish_headers_unreadable_before_enter():
    """Reading headers before enter would ship a carrier without a traceparent
    and silently lose the lineage edge — it must refuse loudly."""
    publish = publisher(CapturingSink())
    pub = publish("OrderPlaced", destination="orders")
    with pytest.raises(RuntimeError, match="inside the 'async with'"):
        _ = pub.headers
    async with pub:  # inside the block it reads fine
        assert pub.headers["event_type"] == "OrderPlaced"


async def test_late_sent_is_ignored_with_a_warning_not_applied():
    sink = CapturingSink()
    publish = publisher(sink)
    pub = publish("OrderPlaced", destination="orders", idempotency_key="K1")
    async with pub:
        pass
    pub.sent("orders/0/99")  # too late — envelope already shipped
    (env,) = sink.envelopes
    assert env.message_id == "K1"  # the fallback, not the late id


def test_publisher_requires_exactly_one_of_sink_or_url():
    with pytest.raises(ValueError):
        ProducerObserver(source_service="s", broker="kafka")
    with pytest.raises(ValueError):
        ProducerObserver(
            source_service="s",
            broker="kafka",
            sink=CapturingSink(),
            observatory_url="http://obs",
        )


# ---- the hoisted pull gate ----------------------------------------------------


class _FixedControl:
    def __init__(self, control: Control) -> None:
        self._control = control

    async def get(self) -> Control:
        return self._control


class _DummyPull(PullEventConsumer):
    async def _poll_loop(self) -> None:  # pragma: no cover - never started
        pass


def _pull(state: ControlState, rate: float | None = None) -> _DummyPull:
    return _DummyPull(
        PullEventConsumerConfig(type="dummy", poll_interval=0.01),
        control=_FixedControl(Control(state, throttle_per_sec=rate)),
    )


async def test_control_gate_skips_cycle_while_paused():
    assert await _pull(ControlState.PAUSED)._control_gate() is None
    assert await _pull(ControlState.DRAINING)._control_gate() is None


async def test_control_gate_passes_running_and_throttled():
    running = await _pull(ControlState.RUNNING)._control_gate()
    assert running is not None and running.state is ControlState.RUNNING
    throttled = await _pull(ControlState.THROTTLED, rate=100)._control_gate()
    assert throttled is not None and throttled.state is ControlState.THROTTLED


async def test_throttle_pace_only_paces_throttled():
    consumer = _pull(ControlState.RUNNING)
    start = time.monotonic()
    await consumer._throttle_pace(Control(ControlState.RUNNING))
    assert time.monotonic() - start < 0.05  # running → no pacing sleep
    await consumer._throttle_pace(Control(ControlState.THROTTLED, throttle_per_sec=100))
    # throttled at 100/s → ~10ms pace; just prove it slept measurably
    assert time.monotonic() - start >= 0.005
