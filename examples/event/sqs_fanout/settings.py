"""Configuration and topology for the fan-out demo.

Everything env-tunable lives here, so the behavioural modules (subscribers,
services, driver) stay about *what happens*, not *where things point*.

The topology is the star of the demo: one source event fans out into four
independent branches, each with its own queue and consuming service.

    OrderPaid ─┬─▶ ShipmentRequested  → shipping-svc
               ├─▶ InvoiceIssued      → billing-svc
               ├─▶ PointsAwarded      → loyalty-svc   (flaky → dead-letters)
               └─▶ ReceiptEmailed     → receipt-svc
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Branch:
    """One leg of the fan-out: an event type routed to a queue and handled by
    a dedicated downstream service."""

    event_type: str
    queue: str
    service: str
    flaky: bool = False


# The queue every trace starts from, and the shared dead-letter queue the flaky
# branch parks its give-ups in.
SOURCE_QUEUE = "q-order-paid"
LOYALTY_DLQ = "q-loyalty-dlq"

BRANCHES: tuple[Branch, ...] = (
    Branch("ShipmentRequested", "q-ship", "shipping-svc"),
    Branch("InvoiceIssued", "q-invoice", "billing-svc"),
    Branch("PointsAwarded", "q-loyalty", "loyalty-svc", flaky=True),
    Branch("ReceiptEmailed", "q-receipt", "receipt-svc"),
)

# The service names stamped onto telemetry for the ingress and the fan-out hub.
INGRESS_SERVICE = "checkout-gateway"
ORDER_SERVICE = "order-svc"


@dataclass(frozen=True)
class Settings:
    """Runtime knobs, all overridable via environment variables."""

    endpoint_url: str = os.getenv("AWS_ENDPOINT_URL", "http://127.0.0.1:4566")
    region: str = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    observatory_url: str = os.getenv("OBSERVATORY_URL", "http://127.0.0.1:8080")
    # Required when the Observatory enforces machine auth; None only works
    # against an open-mode (dev) backend.
    observatory_api_key: str | None = os.getenv("OBSERVATORY_API_KEY")
    orders_per_sec: float = float(os.getenv("DEMO_RATE", "1.5"))


SETTINGS = Settings()
