"""Small helpers for reading fields off an incoming :class:`Message`.

SQS metadata values arrive as ``{"StringValue": "…", "DataType": "String"}``
maps, so a couple of accessors keep the subscribers and wiring readable.
"""

from __future__ import annotations

from typing import Any

from pymidil.event import Message


def _attr(value: Any) -> Any:
    """Unwrap an SQS attribute value (``{"StringValue": …}``) to a plain string."""
    if isinstance(value, dict):
        return value.get("StringValue") or value.get("stringValue")
    return value if value is None else str(value)


def order_id(message: Message) -> str:
    """The business key every event in this demo carries."""
    body = message.body if isinstance(message.body, dict) else {}
    return str(body.get("order_id", "OD-?"))


def receive_count(message: Message) -> int:
    """How many times SQS has delivered this message (1 on first receipt).

    Drives the flaky branch's retry-then-give-up behaviour.
    """
    md = getattr(message, "metadata", {}) or {}
    return int(_attr(md.get("ApproximateReceiveCount")) or "1")


def idempotency_key(message: Message) -> str:
    """Dedup key for the idempotency guard: the ``idempotency_key`` metadata a
    producer set, falling back to the message id."""
    md = getattr(message, "metadata", {}) or {}
    return _attr(md.get("idempotency_key")) or str(getattr(message, "id", ""))
