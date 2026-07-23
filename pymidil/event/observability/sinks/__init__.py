"""Telemetry sinks — where envelopes are shipped (stdout, HTTP, a producer, …)."""

from pymidil.event.observability.sinks.base import TelemetrySink
from pymidil.event.observability.sinks.null import NullTelemetrySink
from pymidil.event.observability.sinks.stdout import StdoutTelemetrySink

__all__ = [
    "TelemetrySink",
    "NullTelemetrySink",
    "StdoutTelemetrySink",
    # HttpTelemetrySink / ProducerTelemetrySink are imported lazily from their
    # modules to avoid pulling optional deps (httpx / a producer) at import time.
]
