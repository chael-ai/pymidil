"""OpenTelemetry trace propagation — the canonical trace plane for events.

Carrier-based inject/extract + produce/consume/replay span helpers. This module
uses the OpenTelemetry **API only**; applications wire the SDK (or call
:func:`configure_tracing`). ``opentelemetry-api`` is a core dependency, and this
module is now on the live dispatch path: ``EventConsumer.dispatch`` opens a
:func:`consumer_span`, producers wrap publish in a :func:`producer_span`, and the
telemetry emitter reads :func:`current_span_ids`. It superseded the bespoke
``event/tracing.py`` (removed in the OTel migration).

The carrier is a flat ``dict[str, str]`` (W3C ``traceparent``), so OTel's default
TextMap getter/setter applies. Transport-specific shapes (e.g. SQS message
attributes) are flattened to this form at the transport edge via the consumer's
``carrier()`` adapter.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Mapping, MutableMapping, Optional, Tuple

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.propagate import extract as _extract
from opentelemetry.propagate import inject as _inject
from opentelemetry.trace import Link, Span, SpanContext, SpanKind, Tracer

TRACER_NAME = "pymidil.event"
DISCONTINUITY_ATTR = "midil.trace.discontinuity"


def get_tracer() -> Tracer:
    return trace.get_tracer(TRACER_NAME)


def coerce_header_value(value: Any) -> Optional[str]:
    """Normalise a carrier value to a flat string.

    Tolerates SQS MessageAttribute shapes (``{"StringValue": "..."}``) so the same
    reader works whether the carrier is flat headers or AWS attribute dicts.
    """
    if value is None:
        return None
    if isinstance(value, Mapping):
        for key in ("StringValue", "stringValue", "Value", "value"):
            if key in value:
                return str(value[key])
        return None
    return str(value)


def _hex(value: int, width: int) -> str:
    return format(value, f"0{width}x")


def span_ids(span_context: SpanContext) -> Tuple[Optional[str], Optional[str]]:
    """(trace_id, span_id) as 32/16-hex strings, or (None, None) if invalid."""
    if not span_context.is_valid:
        return None, None
    return _hex(span_context.trace_id, 32), _hex(span_context.span_id, 16)


def current_trace_ids() -> Tuple[Optional[str], Optional[str]]:
    """(trace_id, span_id) of the active span."""
    return span_ids(trace.get_current_span().get_span_context())


def current_span_ids() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """(trace_id, span_id, parent_span_id) of the active span, or all None.

    Used by the telemetry emitter to fill the envelope from the live span. The
    parent is read from the SDK span (``.parent``); it is None for a root span
    or when no SDK TracerProvider is configured.
    """
    span = trace.get_current_span()
    sc = span.get_span_context()
    if not sc.is_valid:
        return None, None, None
    parent = getattr(span, "parent", None)
    parent_span_id = (
        _hex(parent.span_id, 16) if parent is not None and parent.is_valid else None
    )
    return _hex(sc.trace_id, 32), _hex(sc.span_id, 16), parent_span_id


def inject_headers(carrier: MutableMapping[str, str]) -> MutableMapping[str, str]:
    """Inject the active trace context into a flat string carrier (W3C)."""
    _inject(carrier)
    return carrier


def extract_context(carrier: Mapping[str, str]) -> Context:
    """Extract a remote context from a carrier (empty context if absent)."""
    return _extract(carrier)


@contextmanager
def producer_span(destination: str, *, system: str = "event") -> Iterator[Span]:
    """PRODUCER span around a publish; inject the carrier inside the block."""
    with get_tracer().start_as_current_span(
        f"publish {destination}", kind=SpanKind.PRODUCER
    ) as span:
        span.set_attribute("messaging.system", system)
        span.set_attribute("messaging.destination.name", destination)
        span.set_attribute("messaging.operation", "publish")
        yield span


@contextmanager
def consumer_span(
    carrier: Mapping[str, str], source: str, *, system: str = "event"
) -> Iterator[Tuple[Span, Optional[str]]]:
    """CONSUMER span continuing the carrier's trace.

    Yields ``(span, parent_span_id)``. ``parent_span_id`` is None when the carrier
    had no valid upstream context — flagged on the span as a discontinuity so a
    lost-context hop is visible instead of silently rooting a fresh trace.
    """
    ctx = extract_context(carrier)
    parent_ctx = trace.get_current_span(ctx).get_span_context()
    _, parent_span_id = span_ids(parent_ctx)

    with get_tracer().start_as_current_span(
        f"process {source}", context=ctx, kind=SpanKind.CONSUMER
    ) as span:
        span.set_attribute("messaging.system", system)
        span.set_attribute("messaging.operation", "process")
        if parent_span_id is None:
            span.set_attribute(DISCONTINUITY_ATTR, True)
        yield span, parent_span_id


@contextmanager
def replay_span(
    original_carrier: Mapping[str, str], destination: str, *, system: str = "event"
) -> Iterator[Tuple[Span, SpanContext]]:
    """A PRODUCER span for a DLQ replay, linked to the original message's span.

    A replay is a distinct operation (operator-triggered, temporally separate), so
    it starts its **own** trace rather than grafting onto the original. An OTel
    **Link** back to the original span plus ``replayed_from.*`` attributes record
    the causal relationship explicitly. Yields ``(span, original_span_context)``;
    the caller injects this span's context into the re-sent carrier.
    """
    original_ctx = extract_context(original_carrier)
    original_sc = trace.get_current_span(original_ctx).get_span_context()
    links = [Link(original_sc)] if original_sc.is_valid else []
    with get_tracer().start_as_current_span(
        f"replay {destination}", kind=SpanKind.PRODUCER, links=links
    ) as span:
        span.set_attribute("messaging.system", system)
        span.set_attribute("messaging.operation", "replay")
        if original_sc.is_valid:
            span.set_attribute("replayed_from.trace_id", _hex(original_sc.trace_id, 32))
            span.set_attribute("replayed_from.span_id", _hex(original_sc.span_id, 16))
        yield span, original_sc


def configure_tracing(
    *,
    service_name: str = "pymidil-service",
    sampler_ratio: float = 1.0,
    exporter: Optional[object] = None,
) -> object:
    """Opt-in SDK setup (requires ``opentelemetry-sdk``).

    Apps usually own this; provided for convenience. Defaults to a console exporter.
    """
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    provider = TracerProvider(
        resource=Resource.create({"service.name": service_name}),
        sampler=ParentBased(TraceIdRatioBased(sampler_ratio)),
    )
    provider.add_span_processor(
        BatchSpanProcessor(exporter or ConsoleSpanExporter())  # type: ignore[arg-type]
    )
    trace.set_tracer_provider(provider)
    return provider
