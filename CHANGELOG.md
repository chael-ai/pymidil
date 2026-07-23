# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

## v0.2.0 (2026-07-23)

The Observatory release: pymidil is now the instrumentation and control SDK for
[Midil Observatory](https://midil.io). Everything a consumer or producer does —
success, retry, failure, dead-letter, duplicate — can be observed in the
console, and the console's pause/throttle/drain controls flow back to the SDK.

### Features

- **Observers — instrument consumers you already run** (`pymidil.event.observability`):
  `ConsumerObserver` wraps each delivery of an existing consumer (any broker —
  Kafka, RabbitMQ, SQS, …) in an observation context that emits the same
  telemetry envelope as a pymidil-managed consumer: outcome, wall-clock
  processing time, and W3C trace continuity from the message headers.
  `observe.control` polls the Observatory's control state so pause / throttle /
  drain from the console are honored without adopting pymidil consumers.
  `ProducerObserver` is the emit-side counterpart.
- **Telemetry hooks**: `TelemetryDispatchHook` emits a `TelemetryEnvelope` at
  every dispatch outcome (success / retrying / failed / dlq / duplicate);
  `TelemetryProducerHook` records the emitted leg on producers, so fan-out
  edges are attributed to the emitting service. Pluggable sinks
  (`HttpTelemetrySink`, `ProducerTelemetrySink`, `StdoutTelemetrySink`,
  `NullTelemetrySink`); one-call wiring via `attach_telemetry(bus)` /
  `TelemetrySettings` (env prefix `MIDIL_TELEMETRY_`). The envelope carries
  four distinct identifiers — `id` (observation) · `message_id` (delivery) ·
  `idempotency_key` (logical step) · `trace_id` (transaction across hops) —
  matching the Observatory ingestion contract.
- **API keys (machine auth)**: `api_key="mo_…"` on observers, `HttpTelemetrySink`,
  and the HTTP control source, sent as `X-Api-Key`. The key is issued in the
  Observatory console, selects the organization telemetry lands in, and is
  scoped to telemetry-write + control-read only.
- **OpenTelemetry trace plane** (`pymidil.event.otel`): carrier inject/extract,
  PRODUCER/CONSUMER spans wired into publish and dispatch, cross-service trace
  continuity (a handler that publishes downstream continues the same trace),
  a lost-context discontinuity flag, and opt-in `configure_tracing`.
  `opentelemetry-api` is a core dependency. Consumers expose `carrier()`
  (SQS → message attributes, webhook → HTTP headers), so propagation no longer
  depends on transport-specific `Message` fields.
- **Acknowledgement abstraction** (`pymidil.event.acknowledgement`): every
  `EventConsumer` is an `Acknowledger` with broker-agnostic dispositions
  `ack` / `retry` / `dlq` (`nack` is gone — it conflated retry-or-dead-letter).
  Dispatch is wired success→ack, retryable→retry, non-retryable→dlq;
  `SQSConsumer` implements all three (delete / reset visibility / divert to
  DLQ); `use_acknowledger()` swaps the strategy independently of the ingress
  transport.
- **Idempotency at the dispatch boundary**:
  `consumer.use_idempotency(IdempotencyPolicy(...))` deduplicates deliveries
  for every subscriber type without cross-blocking siblings. Duplicates are
  acked and surfaced via the `on_duplicate` hook (and `duplicate` telemetry).
  `IdempotencyStore` interface with `InMemoryIdempotencyStore` and
  `RedisIdempotencyStore` (atomic `SET NX EX`); claims release on
  retry/failure so redeliveries can re-process. The key is a typed
  `Message.idempotency_key` (falling back to `Message.id`).
- **DLQ + replay causality**: an `on_dead_letter` dispatch stage emits `dlq`
  telemetry; `SQSConsumer.dlq` preserves the trace carrier on the parked
  message; `SQSDlqRedriver` re-drives dead-letters back to the source queue,
  starting a **new** trace OTel-linked to the original and threading
  `replayed_from` through headers onto the envelope — so the Observatory shows
  "replay of trace X" as a first-class link, never a guess.
- **Examples**: [`examples/event/sqs_fanout/`](examples/event/sqs_fanout/) —
  end-to-end fan-out demo (topology, retries, DLQ, idempotency, telemetry,
  console control) on LocalStack; [`examples/event/kafka_observer.py`](examples/event/kafka_observer.py)
  — zero-refactor observation of an existing aiokafka consumer.

### Improvements

- `Message` is now a thin base (id + body + idempotency_key + timestamp):
  broker delivery attributes (`metadata`) moved onto the inbound
  `ConsumerMessage`, where they belong (mirroring `WebhookMessage.headers`),
  so generic dispatch never reaches into transport-specific fields.

### Bug Fixes

- SQS: consumer config `region`/`dlq_region` used `ArnParser.parse` (which does
  not exist) instead of `parse_arn`, raising `AttributeError` on every SQS
  ack/nack.

## v0.1.0 (2026-06-21)

### Features

- Auth: Cognito client credentials flow and JWT verification with a pluggable interface
- Event: Transport-agnostic event bus with SQS, Redis, and webhook producers/consumers
- HTTP: Async HTTP client with configurable retry and backoff strategies
- MidilAPI: FastAPI wrapper enforcing JSONAPI-compliant responses, pagination, and middleware
- JSONAPI: Document and resource serialization/deserialization spec
- Logger: Structured logging with configurable handlers
- CLI: `midil init`, `midil launch`, and `midil version` commands for project scaffolding and service management
- Settings: Environment-variable-driven configuration system
