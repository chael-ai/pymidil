# SQS fan-out demo

A practical, end-to-end tour of **pymidil** feeding the **Midil Observatory**.

Once an order is paid, several *independent* things must happen — ship it, bill
it, award loyalty points, email a receipt. `order-svc` consumes one `OrderPaid`
event and **fans it out** into four events, each handled by its own service:

```
OrderPaid ─┬─▶ ShipmentRequested  → shipping-svc
           ├─▶ InvoiceIssued      → billing-svc
           ├─▶ PointsAwarded      → loyalty-svc   (flaky → dead-letters)
           └─▶ ReceiptEmailed     → receipt-svc
```

One order = one trace whose graph branches one-into-four — the shape a lineage
graph shows at a glance and a flat log can't. The loyalty branch fails for ~30%
of orders (retried twice, then dead-lettered), so some traces show three green
branches and one red: *paid and shipped, but loyalty points failed.*

## What it teaches about pymidil

| Concept | Where to look |
|---|---|
| **Subscribers** are classes, not callbacks — `EventSubscriber` with a `should_handle → handle → on_success/on_error` lifecycle | [`subscribers.py`](subscribers.py) |
| **Producers** publish events; a `TelemetryProducerHook` records the "emitted" step | [`driver.py`](driver.py), [`services.py`](services.py) |
| **Consumers** bind a subscriber to a queue; a `TelemetryDispatchHook` records each outcome | [`services.py`](services.py) |
| **Retry vs dead-letter** is decided by the exception you raise: `RetryableEventError` → redelivered; anything else → DLQ | [`subscribers.py`](subscribers.py) `FlakyLoyaltySubscriber` |
| **Idempotency** — an `IdempotencyPolicy` so redeliveries don't double-process | [`services.py`](services.py) |
| **Tracing** — one trace id threaded producer→consumer→producer | [`__main__.py`](__main__.py) |

## Module map

- `settings.py` — endpoints, cadence, and the fan-out **topology** (`BRANCHES`).
- `messages.py` — helpers for reading fields off an incoming message.
- `subscribers.py` — the **business logic** as `EventSubscriber` classes.
- `services.py` — the **composition root**: snaps transport + telemetry + idempotency + subscriber together.
- `driver.py` — the ingress that emits `OrderPaid` (the producer side, minimal).
- `infra.py` — LocalStack session + queue creation.
- `__main__.py` — the runtime (start, drive, shut down).

## Run it

```bash
# 1. LocalStack SQS
docker run -d -p 127.0.0.1:4566:4566 -e SERVICES=sqs localstack/localstack:3

# 2. Observatory (in midil-observatory-api)
uvicorn observatory.asgi:app --port 8080

# 3. This demo (from the pymidil repo root)
python -m examples.event.sqs_fanout
```

Then open the Observatory's **Event Trace Graph** and pick a recent trace — you'll
see the one-into-four branch, mostly green with the occasional red loyalty leg.

Tunable via env: `AWS_ENDPOINT_URL`, `OBSERVATORY_URL`, `DEMO_RATE` (orders/sec).

## Tests

The subscribers are plain classes, so their logic is unit-testable without any
infrastructure:

```bash
python -m pytest examples/event/sqs_fanout/test_subscribers.py
```
