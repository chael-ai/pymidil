"""Event ↔ wire mapping — the producer/consumer boundary contract.

An :class:`Event` travels as CloudEvents *binary content mode*: its ``data`` is
the message body, its attributes ride in the transport's header/attribute
side-channel (SQS message attributes, HTTP headers, a Redis envelope). This
module is the single place that mapping is defined, so producers stamp and
consumers reconstruct one agreed shape — no transport re-invents it.

Values are strings (transport attributes are stringly); ``event_to_wire``
serializes, ``wire_to_event`` parses back with fallbacks for foreign producers
that didn't use pymidil.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

from pymidil.event.core import Event

#: Canonical wire attribute names — the CloudEvents-shaped contract a producer
#: stamps and a consumer's transport adapter reads back to reconstruct the
#: ``Event``. Data rides in the message body; these attributes ride in the
#: transport's header/attribute side-channel (CloudEvents "binary content
#: mode"), so an intermediary can route/filter without decoding the body. They
#: live here, beside the mapping (``event_to_wire`` / ``wire_to_event``) that is
#: their only consumer — names and mapping are one contract, one home.
EVENT_ID_FIELD = "event_id"
EVENT_SOURCE_FIELD = "event_source"
EVENT_TYPE_FIELD = "event_type"
EVENT_SUBJECT_FIELD = "event_subject"
EVENT_TIME_FIELD = "event_time"
IDEMPOTENCY_KEY_FIELD = "idempotency_key"

#: Extension attributes are stamped with this prefix so they round-trip without
#: colliding with the core attribute names above.
EXT_PREFIX = "ext_"

_CORE_ATTRS = {
    EVENT_ID_FIELD,
    EVENT_SOURCE_FIELD,
    EVENT_SUBJECT_FIELD,
    EVENT_TIME_FIELD,
    EVENT_TYPE_FIELD,
    IDEMPOTENCY_KEY_FIELD,
}


def event_to_wire(event: Event) -> dict[str, str]:
    """The transport attributes carrying ``event``'s identity/metadata."""
    attrs: dict[str, str] = {
        EVENT_ID_FIELD: event.id,
        EVENT_SOURCE_FIELD: event.source,
        EVENT_TYPE_FIELD: event.type,
        EVENT_TIME_FIELD: event.time.isoformat(),
    }
    if event.subject:
        attrs[EVENT_SUBJECT_FIELD] = event.subject
    if event.idempotency_key:
        attrs[IDEMPOTENCY_KEY_FIELD] = event.idempotency_key
    for key, value in event.extensions.items():
        attrs[f"{EXT_PREFIX}{key}"] = str(value)
    return attrs


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def wire_to_event(
    attrs: Mapping[str, str],
    *,
    data: Any,
    fallback_id: str,
    fallback_time: datetime,
) -> Event:
    """Reconstruct an ``Event`` from flat (already-unwrapped) wire attributes.

    ``fallback_id``/``fallback_time`` cover foreign producers that didn't stamp
    the pymidil attributes (e.g. the transport's own delivery id / timestamp).
    Extension attributes (``ext_*``) are restored; ``replayed_from`` — set by the
    DLQ path — is carried through as an extension too.
    """
    extensions = {
        key[len(EXT_PREFIX) :]: value
        for key, value in attrs.items()
        if key.startswith(EXT_PREFIX)
    }
    if "replayed_from" in attrs:
        extensions.setdefault("replayed_from", attrs["replayed_from"])
    return Event(
        id=attrs.get(EVENT_ID_FIELD) or fallback_id,
        source=attrs.get(EVENT_SOURCE_FIELD) or "unknown",
        type=attrs.get(EVENT_TYPE_FIELD) or "unknown",
        data=data,
        subject=attrs.get(EVENT_SUBJECT_FIELD),
        time=_parse_time(attrs.get(EVENT_TIME_FIELD)) or fallback_time,
        idempotency_key=attrs.get(IDEMPOTENCY_KEY_FIELD),
        extensions=extensions,
    )
