"""Telemetry emitter (A2).

A concrete ``DispatchHook`` that builds a :class:`TelemetryEnvelope` at each
terminal stage of the dispatch lifecycle and ships it to a ``TelemetrySink``.
Reads the active trace (bound by ``EventConsumer.dispatch``) so every envelope
is correctly correlated.

Stages mapped today: complete→success, failure→failed, retry→retrying. ``dlq``
and ``duplicate`` are produced by later milestones (DLQ replay / idempotency).
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from loguru import logger

from pymidil.event.context import get_current_event
from pymidil.event.observability.envelope import EventStatus, TelemetryEnvelope
from pymidil.event.observability.hooks import DispatchHook
from pymidil.event.observability.protocols import MessageProtocol
from pymidil.event.observability.sinks.base import TelemetrySink
from pymidil.event.tracing import coerce_header_value, current_trace
from pymidil.utils.time import utcnow


class TelemetryDispatchHook(DispatchHook):
    """Emit telemetry envelopes from the dispatch lifecycle.

    Args:
        sink: Where envelopes are shipped.
        source_service: The emitting service (e.g. ``settlement-svc``).
        consumer: Logical consumer name; defaults to ``source_service``.
        broker: Transport override; defaults to the consumer's transport type
            (the ``consumer_name`` the dispatcher passes, e.g. ``sqs``).
        include_payload: Whether to attach the message body to the envelope.
    """

    def __init__(
        self,
        sink: TelemetrySink,
        *,
        source_service: str,
        consumer: Optional[str] = None,
        broker: Optional[str] = None,
        include_payload: bool = True,
    ) -> None:
        self._sink = sink
        self._source_service = source_service
        self._consumer = consumer or source_service
        self._broker = broker
        self._include_payload = include_payload

    async def on_complete(
        self, message: MessageProtocol, consumer_name: str, duration_ms: float
    ) -> None:
        await self._emit(
            message, consumer_name, EventStatus.SUCCESS, processing_time_ms=duration_ms
        )

    async def on_duplicate(self, message: MessageProtocol, consumer_name: str) -> None:
        await self._emit(message, consumer_name, EventStatus.DUPLICATE)

    async def on_failure(
        self, message: MessageProtocol, consumer_name: str, error: Exception
    ) -> None:
        reason, klass = self._describe_error(error)
        await self._emit(
            message,
            consumer_name,
            EventStatus.FAILED,
            failure_reason=reason,
            failure_class=klass,
        )

    async def on_retry(
        self, message: MessageProtocol, consumer_name: str, errors: list
    ) -> None:
        first = errors[0] if errors else None
        reason, klass = self._describe_error(first)
        await self._emit(
            message,
            consumer_name,
            EventStatus.RETRYING,
            failure_reason=reason,
            failure_class=klass,
        )

    async def on_dead_letter(
        self,
        message: MessageProtocol,
        consumer_name: str,
        error: Exception | None = None,
    ) -> None:
        if error is not None:
            reason, klass = self._describe_error(error)
        else:
            reason, klass = "moved to dead-letter queue", "DeadLetter"
        await self._emit(
            message,
            consumer_name,
            EventStatus.DLQ,
            failure_reason=reason,
            failure_class=klass,
        )

    async def _emit(
        self,
        message: MessageProtocol,
        consumer_name: str,
        status: EventStatus,
        *,
        processing_time_ms: Optional[float] = None,
        failure_reason: Optional[str] = None,
        failure_class: Optional[str] = None,
    ) -> None:
        envelope = self._build_envelope(
            message,
            consumer_name,
            status,
            processing_time_ms=processing_time_ms,
            failure_reason=failure_reason,
            failure_class=failure_class,
        )
        try:
            await self._sink.emit(envelope)
        except Exception as exc:  # telemetry must never break dispatch
            logger.warning(
                f"[telemetry] sink emit failed for {envelope.event_id}: {exc}"
            )

    def build_envelope(
        self,
        message: MessageProtocol,
        consumer_name: str,
        status: EventStatus,
        **fields: Any,
    ) -> TelemetryEnvelope:
        """Public builder — useful for emitting dlq/duplicate from other call sites."""
        return self._build_envelope(message, consumer_name, status, **fields)

    def _build_envelope(
        self,
        message: MessageProtocol,
        consumer_name: str,
        status: EventStatus,
        *,
        processing_time_ms: Optional[float] = None,
        failure_reason: Optional[str] = None,
        failure_class: Optional[str] = None,
    ) -> TelemetryEnvelope:
        metadata: Mapping[str, Any] = getattr(message, "metadata", {}) or {}
        trace = current_trace()
        return TelemetryEnvelope(
            event_id=str(message.id),
            event_type=self._event_type(metadata, consumer_name),
            status=status,
            broker=self._broker or consumer_name,
            consumer=self._consumer,
            source_service=self._source_service,
            occurred_at=getattr(message, "timestamp", None) or utcnow(),
            attempts=self._attempts(metadata),
            processing_time_ms=processing_time_ms,
            trace_id=trace.trace_id if trace else None,
            span_id=trace.span_id if trace else None,
            parent_span_id=trace.parent_span_id if trace else None,
            idempotency_key=getattr(message, "idempotency_key", None)
            or coerce_header_value(metadata.get("idempotency_key"))
            or str(message.id),
            failure_reason=failure_reason,
            failure_class=failure_class,
            payload=getattr(message, "body", None) if self._include_payload else None,
            metadata=self._clean_metadata(metadata),
        )

    @staticmethod
    def _event_type(metadata: Mapping[str, Any], consumer_name: str) -> str:
        from_meta = coerce_header_value(metadata.get("event_type"))
        if from_meta:
            return from_meta
        event = get_current_event()
        if event is not None and event.event_type:
            return event.event_type
        return consumer_name

    @staticmethod
    def _attempts(metadata: Mapping[str, Any]) -> int:
        raw = metadata.get("ApproximateReceiveCount") or metadata.get("attempts")
        value = coerce_header_value(raw)
        try:
            return int(value) if value is not None else 1
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _clean_metadata(metadata: Mapping[str, Any]) -> dict:
        skip = {"traceparent", "x-correlation-id", "event_type"}
        cleaned: dict[str, Any] = {}
        for key, value in metadata.items():
            if str(key).lower() in skip:
                continue
            flat = coerce_header_value(value)
            if flat is not None:
                cleaned[str(key)] = flat
        return cleaned

    @staticmethod
    def _describe_error(
        error: Optional[BaseException],
    ) -> tuple[Optional[str], Optional[str]]:
        if error is None:
            return None, None
        if isinstance(error, BaseExceptionGroup):
            inner = error.exceptions[0] if error.exceptions else None
            reason = "; ".join(str(e) for e in error.exceptions) or str(error)
            klass = type(inner).__name__ if inner else type(error).__name__
            return reason, klass
        return str(error), type(error).__name__
