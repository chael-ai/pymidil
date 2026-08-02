"""Broker-agnostic observation for consumers AND producers pymidil does not manage.

Teams with existing messaging code (aiokafka, confluent-kafka, pika, …)
integrate with Midil by *wrapping* their handler/send, not by rewriting onto
pymidil's classes. :class:`ConsumerObserver` wraps consumption::

    observe = ConsumerObserver(
        observatory_url="http://observatory:8080",
        consumer="orders-worker",
        broker="kafka",
    )

    async for record in kafka_consumer:                      # their loop, untouched
        async with observe(record.offset, "OrderPlaced", headers=record.headers):
            await their_existing_handler(record)             # their code, untouched

:class:`ProducerObserver` wraps the send — completing the lineage graph with
the *produced* leg (the ingress node) and making publish failures observable::

    publish = ProducerObserver(
        observatory_url="http://observatory:8080",
        source_service="checkout-gateway",
        broker="kafka",
    )

    async with publish("OrderPlaced", destination="orders", payload=order) as pub:
        md = await producer.send_and_wait(          # their producer, untouched
            "orders", value, headers=[(k, v.encode()) for k, v in pub.headers.items()]
        )
        pub.sent(f"orders/{md.partition}/{md.offset}")   # groups with the delivery

Sync call sites (Django, Celery, …) use the same objects with ``with`` instead
of ``async with``, or the helpers in
:mod:`pymidil.event.observability.sync_api`::

    from pymidil.event.observability import observe_publish, observe_consume

    result = observe_publish(
        "OrderPlaced",
        destination="orders",
        payload=order,
        idempotency_key="OD-1:OrderPlaced",
        send=enqueue,
    )

    observe_consume(
        message_id,
        "OrderPlaced",
        consumer="orders-worker",
        payload=order,
        handle=process,
    )

Each observed delivery gets, automatically:

* **trace continuity** — the W3C ``traceparent`` in the delivery headers is
  extracted and a CONSUMER span bound around the handler, so envelopes carry
  real trace ids (without this, ``current_span_ids()`` reads nothing and the
  lineage graph silently loses the hop);
* **outcome → status** — clean exit → ``success``; exceptions are classified
  (:func:`default_classification`, overridable) and re-raised, never swallowed;
* **timing** — wall-clock ``processing_time_ms``;
* **control** — ``observe.control`` polls the Observatory's desired state so
  the loop can honour pause/throttle/drain (see ``HttpControlSource``).

Design notes: this module *composes* the existing semantic core — the
status vocabulary and envelope construction live only in
:class:`TelemetryDispatchHook`, so observed and pymidil-managed consumers emit
byte-identical telemetry. ``broker`` is data (a label), which is what lets one
observer serve every transport. Telemetry failures are isolated: an emission
error is logged, never raised into the caller's consume loop.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import (
    Any,
    Callable,
    Dict,
    Iterable,
    Mapping,
    Optional,
    Tuple,
    Union,
)

from loguru import logger

from pymidil.event.control import ControlSource, HttpControlSource, NullControlSource
from pymidil.event.exceptions import NonRetryableEventError, RetryableEventError
from pymidil.event.observability.emitter import (
    TelemetryDispatchHook,
    TelemetryProducerHook,
)
from pymidil.event.observability.envelope import EventStatus
from pymidil.event.observability.hooks import PublishRecord
from pymidil.event.observability.sinks.base import TelemetrySink
from pymidil.event.otel import (
    coerce_header_value,
    consumer_span,
    current_span_ids,
    inject_headers,
    override_span_ids,
    producer_span,
)
from pymidil.utils.sync import run_sync

#: Anything a transport hands back as headers: a mapping (HTTP, SQS attribute
#: dicts) or an iterable of key/value pairs (Kafka's ``list[tuple[str, bytes]]``).
HeadersLike = Union[Mapping[str, Any], Iterable[Tuple[Any, Any]], None]

#: Maps a handler exception to the telemetry status it should record.
ExceptionClassifier = Callable[[BaseException], EventStatus]


def default_classification(error: BaseException) -> EventStatus:
    """The honest default for consumers Midil does not manage.

    pymidil's own signals keep their meaning when a team opts into them;
    any other exception records ``failed`` — "this attempt failed" — because
    the observer cannot know whether the team's broker config will retry or
    dead-letter it. Teams that do know pass their own classifier.
    """
    if isinstance(error, RetryableEventError):
        return EventStatus.RETRYING
    if isinstance(error, NonRetryableEventError):
        return EventStatus.DLQ
    return EventStatus.FAILED


def _normalize_headers(headers: HeadersLike) -> Dict[str, str]:
    """Flatten transport headers to the ``dict[str, str]`` W3C carrier shape.

    Tolerates Kafka's bytes keys/values, HTTP header mappings, and SQS
    MessageAttribute dicts (via :func:`coerce_header_value`). Undecodable or
    empty values are dropped rather than raised on.
    """
    if not headers:
        return {}
    items = headers.items() if isinstance(headers, Mapping) else headers
    flat: Dict[str, str] = {}
    for key, value in items:
        name = key.decode() if isinstance(key, (bytes, bytearray)) else str(key)
        if isinstance(value, (bytes, bytearray)):
            try:
                text: Optional[str] = value.decode()
            except UnicodeDecodeError:
                continue
        else:
            text = coerce_header_value(value)
        if text is not None:
            flat[name] = text
    return flat


@dataclass(frozen=True)
class ObservedMessage:
    """The minimal message shape the telemetry emitter reads (MessageProtocol)."""

    id: str
    body: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    idempotency_key: Optional[str] = None
    timestamp: Optional[datetime] = None


class _UnspecifiedFailure(Exception):
    """Placeholder error when a delivery is marked failed without an exception."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return "handler reported failure"


class Observation:
    """One observed delivery: an async context manager around the handler.

    Entering binds the CONSUMER span (trace continuity) and starts the clock;
    exiting resolves the outcome, emits exactly one telemetry envelope, and
    closes the span. Handler exceptions always propagate — observation never
    changes the caller's control flow.

    When the handler resolves the outcome itself (caught the error, routed the
    message to its own retry/DLQ topic), record that explicitly::

        async with observe(...) as obs:
            try:
                await handler(record)
            except TransientBackendError as exc:
                obs.mark(EventStatus.RETRYING, error=exc)
                ...their redelivery logic...
    """

    def __init__(
        self,
        *,
        hook: TelemetryDispatchHook,
        consumer_name: str,
        message: ObservedMessage,
        carrier: Mapping[str, str],
        classify: ExceptionClassifier,
    ) -> None:
        self._hook = hook
        self._consumer_name = consumer_name
        self._message = message
        self._carrier = carrier
        self._classify = classify
        self._marked: Optional[Tuple[EventStatus, Optional[BaseException]]] = None
        self._start = 0.0
        self._span_cm: Any = None
        self._entered = False

    def mark(self, status: EventStatus, error: Optional[BaseException] = None) -> None:
        """Explicitly record this delivery's outcome, overriding inference."""
        self._marked = (status, error)

    def _enter(self) -> "Observation":
        # Single-use: reusing one Observation would leak span context across
        # deliveries and let a stale mark() win over the next outcome. Like an
        # OTel span, observe each delivery under its own ``with`` / ``async with``
        # and don't interleave two observations within one task.
        if self._entered:
            raise RuntimeError(
                "Observation is single-use — call observe(...) once per delivery"
            )
        self._entered = True
        self._start = time.monotonic()
        # Continue the upstream trace (or start a flagged-discontinuity root) so
        # the envelope's trace ids come from a real active span.
        self._span_cm = consumer_span(self._carrier, self._consumer_name)
        self._span_cm.__enter__()
        return self

    async def __aenter__(self) -> "Observation":
        return self._enter()

    def __enter__(self) -> "Observation":
        """Sync twin of :meth:`__aenter__` for Django / Celery call sites."""
        return self._enter()

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        try:
            outcome = self._resolve(exc)
            if outcome is not None:
                status, error = outcome
                # Emit while the span is still active — current_span_ids() reads it.
                await self._emit(status, error)
        except Exception as emit_error:  # observation must never break consumption
            logger.warning(
                f"[observer] telemetry emission failed for "
                f"{self._message.id}: {emit_error}"
            )
        finally:
            self._span_cm.__exit__(exc_type, exc, tb)
        return False  # never swallow the handler's exception

    def __exit__(self, exc_type, exc, tb) -> bool:
        # Close the OTel span in this context BEFORE asyncio.run(emit).
        # Leaving the span open across asyncio.run copies ContextVars and
        # breaks detach ("Token was created in a different Context").
        outcome = self._resolve(exc)
        span_ids = current_span_ids() if outcome is not None else None
        try:
            self._span_cm.__exit__(exc_type, exc, tb)
        finally:
            self._span_cm = None
        if outcome is None:
            return False
        status, error = outcome
        try:
            with override_span_ids(span_ids or (None, None, None)):
                run_sync(self._emit(status, error))
        except Exception as emit_error:  # observation must never break consumption
            logger.warning(
                f"[observer] telemetry emission failed for "
                f"{self._message.id}: {emit_error}"
            )
        return False

    def _resolve(
        self, exc: Optional[BaseException]
    ) -> Optional[Tuple[EventStatus, Optional[BaseException]]]:
        """The delivery's outcome: an explicit mark wins; otherwise classify the
        exception; a clean, unmarked exit is a success.

        Returns ``None`` for cancellation/shutdown (``CancelledError`` and other
        non-``Exception`` ``BaseException``\\s): that is the *process* stopping,
        not a handler outcome — native dispatch lets it propagate without
        telemetry, and so do we, or every deploy would fabricate ``failed``
        envelopes for its in-flight messages.
        """
        if self._marked is not None:
            return self._marked
        if exc is None:
            return EventStatus.SUCCESS, None
        if not isinstance(exc, Exception):
            return None
        return self._classify(exc), exc

    async def _emit(self, status: EventStatus, error: Optional[BaseException]) -> None:
        message, name = self._message, self._consumer_name
        duration_ms = (time.monotonic() - self._start) * 1000.0
        if status is EventStatus.SUCCESS:
            await self._hook.on_complete(message, name, duration_ms=duration_ms)
        elif status is EventStatus.RETRYING:
            await self._hook.on_retry(message, name, errors=[error] if error else [])
        elif status is EventStatus.DLQ:
            await self._hook.on_dead_letter(message, name, error=error)
        elif status is EventStatus.DUPLICATE:
            await self._hook.on_duplicate(message, name)
        else:  # FAILED
            await self._hook.on_failure(message, name, error or _UnspecifiedFailure())


class ConsumerObserver:
    """Midil integration for a consumer you already run — any broker.

    One instance per logical consumer; call it per delivery to get an
    :class:`Observation` context manager (see module docstring for the loop).

    Args:
        consumer: Logical consumer name as it should appear in the Observatory
            (e.g. ``orders-worker``). Also the control-plane identity.
        broker: Transport label (``kafka``, ``rabbitmq``, ``sqs``, …) — pure
            data on the envelope; adding a broker needs no new code here.
        observatory_url: Base URL of the Midil Observatory. Builds the HTTP
            telemetry sink and the control source. Mutually exclusive with
            ``sink``.
        sink: A pre-built :class:`TelemetrySink` for custom transports/auth.
            When used, ``control`` defaults to a no-op source (pass an
            ``HttpControlSource`` explicitly to keep pause/throttle).
        source_service: Emitting service for attribution; defaults to
            ``consumer``.
        classify: Exception → :class:`EventStatus` mapping; defaults to
            :func:`default_classification`.
        include_payload: Attach message bodies to envelopes (default True).
        control: Explicit :class:`ControlSource` override.

    Attributes:
        control: The consumer's control source. Poll it in the consume loop —
            ``(await observe.control.get()).state.should_pull`` — to honour
            pause/throttle/drain from the console.
    """

    def __init__(
        self,
        *,
        consumer: str,
        broker: str,
        observatory_url: Optional[str] = None,
        sink: Optional[TelemetrySink] = None,
        api_key: Optional[str] = None,
        source_service: Optional[str] = None,
        classify: Optional[ExceptionClassifier] = None,
        include_payload: bool = True,
        control: Optional[ControlSource] = None,
    ) -> None:
        if (sink is None) == (observatory_url is None):
            raise ValueError("provide exactly one of observatory_url or sink")
        if api_key is not None and observatory_url is None:
            raise ValueError(
                "api_key applies only with observatory_url — configure your "
                "sink/control source directly instead"
            )
        if sink is None:
            # Local import: the HTTP sink lazily requires httpx; keep this module
            # importable without the optional http dependency.
            from pymidil.event.observability.sinks.http import HttpTelemetrySink

            sink = HttpTelemetrySink(observatory_url, api_key=api_key)  # type: ignore[arg-type]
        self._sink = sink
        self._consumer = consumer
        self._classify: ExceptionClassifier = classify or default_classification
        # The single semantic core: observed consumers reuse the exact same
        # outcome→envelope mapping as pymidil-managed ones.
        self._hook = TelemetryDispatchHook(
            sink,
            source_service=source_service or consumer,
            consumer=consumer,
            broker=broker,
            include_payload=include_payload,
        )
        if control is not None:
            self.control: ControlSource = control
        elif observatory_url is not None:
            # The control poll is a data-plane surface — same key as the sink.
            self.control = HttpControlSource(observatory_url, consumer, api_key=api_key)
        else:
            self.control = NullControlSource()

    def __call__(
        self,
        message_id: Union[str, int],
        event_type: str,
        *,
        headers: HeadersLike = None,
        payload: Any = None,
        idempotency_key: Optional[str] = None,
        attempts: Optional[int] = None,
        occurred_at: Optional[datetime] = None,
    ) -> Observation:
        """Observe one delivery. Use as ``async with observe(...) [as obs]:``.

        Args:
            message_id: The transport's delivery id (Kafka: e.g.
                ``f"{topic}/{partition}/{offset}"``).
            event_type: Business event name shown across the Observatory.
            headers: Delivery headers — the W3C ``traceparent`` is extracted
                from here for trace continuity.
            payload: Message body (attached when ``include_payload``).
            idempotency_key: Business dedup key; defaults to ``message_id``
                when omitted.
            attempts: Delivery attempt number, if the transport exposes one.
            occurred_at: Message timestamp; defaults to emission time.
        """
        carrier = _normalize_headers(headers)
        metadata: Dict[str, Any] = dict(carrier)
        metadata["event_type"] = event_type
        if attempts is not None:
            metadata["attempts"] = str(attempts)
        resolved_key = (
            str(idempotency_key) if idempotency_key is not None else str(message_id)
        )
        message = ObservedMessage(
            id=str(message_id),
            body=payload,
            metadata=metadata,
            idempotency_key=resolved_key,
            timestamp=occurred_at,
        )
        return Observation(
            hook=self._hook,
            consumer_name=self._consumer,
            message=message,
            carrier=carrier,
            classify=self._classify,
        )

    async def aclose(self) -> None:
        """Release the sink's and control source's network resources."""
        await self._sink.aclose()
        close = getattr(self.control, "aclose", None)
        if close is not None:
            await close()

    def close(self) -> None:
        """Sync twin of :meth:`aclose`."""
        run_sync(self.aclose())


class PublishObservation:
    """One observed publish: an async context manager around the send.

    Entering injects the trace context into :attr:`headers` (put those on the
    wire — that's what stitches the downstream consumer into the lineage) and
    opens a PRODUCER span; exiting emits exactly one ``produced`` envelope —
    success on a clean exit, ``failed`` when the send raised (re-raised, never
    swallowed).

    Call :meth:`sent` with the transport's delivery id once the send returns —
    the produced record then groups with the consumer records for the same
    delivery, which is how the trace graph draws the ingress edge.

    Trace-propagation parity with pymidil's own producers: the *enclosing*
    context (the consumer span, when publishing from inside a handler) is what
    goes on the wire, keeping cross-service lineage a clean consumer→consumer
    chain; the producer span records the publish itself.
    """

    def __init__(
        self,
        *,
        hook: TelemetryProducerHook,
        producer_name: str,
        destination: str,
        event_type: str,
        payload: Any,
        idempotency_key: Optional[str],
        headers: HeadersLike,
    ) -> None:
        self._hook = hook
        self._producer_name = producer_name
        self._destination = destination
        self._payload = payload
        self._message_id: Optional[str] = None
        self._start = 0.0
        self._span_cm: Any = None
        self._entered = False
        self._emitted = False
        # Wire headers: the team's own + the routing keys pymidil producers
        # send (event_type / idempotency_key) — the emitter and any downstream
        # observer read them from here.
        self._headers = _normalize_headers(headers)
        self._headers.setdefault("event_type", event_type)
        if idempotency_key is not None:
            self._headers.setdefault("idempotency_key", idempotency_key)

    @property
    def headers(self) -> Dict[str, str]:
        """Flat string headers to put on the wire (traceparent included).

        Only readable inside the ``async with`` block — the trace context is
        injected on enter, so an earlier read would silently ship headers
        without a traceparent and lose the lineage edge.
        """
        if not self._entered:
            raise RuntimeError(
                "read pub.headers inside the 'async with' block — the trace "
                "context is injected on enter"
            )
        return dict(self._headers)

    def sent(self, message_id: Union[str, int]) -> None:
        """Record the transport's delivery id (e.g. ``topic/partition/offset``)
        so the produced record groups with the delivery's consumer records.

        Must be called inside the ``async with`` block (i.e. before the envelope
        is emitted on exit); a later call can't retroactively fix the
        already-shipped record, so it is ignored with a warning.
        """
        if self._emitted:
            logger.warning(
                f"[observer] sent({message_id!r}) after the publish observation "
                f"closed — the envelope already shipped without it; call sent() "
                f"inside the 'async with' block"
            )
            return
        self._message_id = str(message_id)

    def _enter(self) -> "PublishObservation":
        if self._entered:
            raise RuntimeError(
                "PublishObservation is single-use — call publish(...) once per send"
            )
        self._entered = True
        # Inject the ENCLOSING context before opening the producer span (see
        # class docstring) — the wire carries the upstream consumer's span.
        inject_headers(self._headers)
        self._span_cm = producer_span(self._destination)
        self._span_cm.__enter__()
        self._start = time.monotonic()
        return self

    async def __aenter__(self) -> "PublishObservation":
        return self._enter()

    def __enter__(self) -> "PublishObservation":
        """Sync twin of :meth:`__aenter__` for Django / Celery call sites."""
        return self._enter()

    async def _emit_outcome(self, exc: Optional[BaseException]) -> None:
        if exc is not None and not isinstance(exc, Exception):
            return  # cancellation / shutdown — not a publish outcome
        record = PublishRecord(
            destination=self._destination,
            payload=self._payload,
            metadata=self._headers,
            message_id=self._message_id,
            duration_ms=(time.monotonic() - self._start) * 1000.0,
        )
        if exc is None:
            await self._hook.on_publish(record, self._producer_name)
        else:
            await self._hook.on_publish_error(record, self._producer_name, exc)

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self._emitted = True  # from here on, a late sent() can't reach the wire
        try:
            await self._emit_outcome(exc)
        except Exception as emit_error:  # observation must never break the send path
            logger.warning(
                f"[observer] producer telemetry emission failed for "
                f"{self._destination}: {emit_error}"
            )
        finally:
            self._span_cm.__exit__(exc_type, exc, tb)
        return False  # never swallow the send's exception

    def __exit__(self, exc_type, exc, tb) -> bool:
        # Close the OTel span before asyncio.run(emit) — see Observation.__exit__.
        self._emitted = True
        span_ids = current_span_ids()
        try:
            self._span_cm.__exit__(exc_type, exc, tb)
        finally:
            self._span_cm = None
        try:
            with override_span_ids(span_ids):
                run_sync(self._emit_outcome(exc))
        except Exception as emit_error:  # observation must never break the send path
            logger.warning(
                f"[observer] producer telemetry emission failed for "
                f"{self._destination}: {emit_error}"
            )
        return False


class ProducerObserver:
    """Midil integration for a producer you already run — any broker.

    The produce-side twin of :class:`ConsumerObserver`: one instance per
    publishing service; call it per send to get a :class:`PublishObservation`
    (see module docstring for the loop). Emits the ``produced`` leg of each
    event's lifecycle — the trace graph's ingress node — and records publish
    failures, which are otherwise invisible.

    Args:
        source_service: The publishing service as it should appear in the
            Observatory (e.g. ``checkout-gateway``).
        broker: Transport label (``kafka``, ``rabbitmq``, …) — pure data.
        observatory_url: Base URL of the Midil Observatory. Mutually exclusive
            with ``sink``.
        sink: A pre-built :class:`TelemetrySink` for custom transports/auth.
        include_payload: Attach published payloads to envelopes (default True).
    """

    def __init__(
        self,
        *,
        source_service: str,
        broker: str,
        observatory_url: Optional[str] = None,
        sink: Optional[TelemetrySink] = None,
        api_key: Optional[str] = None,
        include_payload: bool = True,
    ) -> None:
        if (sink is None) == (observatory_url is None):
            raise ValueError("provide exactly one of observatory_url or sink")
        if api_key is not None and observatory_url is None:
            raise ValueError(
                "api_key applies only with observatory_url — configure your sink directly"
            )
        if sink is None:
            from pymidil.event.observability.sinks.http import HttpTelemetrySink

            sink = HttpTelemetrySink(observatory_url, api_key=api_key)  # type: ignore[arg-type]
        self._sink = sink
        self._source_service = source_service
        self._hook = TelemetryProducerHook(
            sink,
            source_service=source_service,
            broker=broker,
            include_payload=include_payload,
        )

    def __call__(
        self,
        event_type: str,
        *,
        destination: str,
        payload: Any = None,
        idempotency_key: Optional[str] = None,
        headers: HeadersLike = None,
    ) -> PublishObservation:
        """Observe one send. Use as ``async with publish(...) as pub:``.

        Args:
            event_type: Business event name (rides the wire headers too, like
                pymidil's own producers).
            destination: Topic/queue name — the PRODUCER span's target.
            payload: The published body (attached when ``include_payload``).
            idempotency_key: Business dedup key to stamp on the wire headers.
                Generated when omitted.
            headers: The team's own outgoing headers to merge, if any.
        """
        return PublishObservation(
            hook=self._hook,
            producer_name=self._source_service,
            destination=destination,
            event_type=event_type,
            payload=payload,
            idempotency_key=idempotency_key or str(uuid.uuid4()),
            headers=headers,
        )

    async def aclose(self) -> None:
        """Release the sink's network resources."""
        await self._sink.aclose()

    def close(self) -> None:
        """Sync twin of :meth:`aclose`."""
        run_sync(self.aclose())
