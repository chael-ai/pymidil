# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Changed

- Telemetry contract: renamed `TelemetryEnvelope.event_id` → **`message_id`**
  (breaking, pre-1.0). The field always carried the per-delivery transport id
  (SQS `MessageId` / webhook body hash), not a "business event id shared across
  hops" as its old description claimed. The four identifiers now each name their
  true scope: `id` (observation) · `message_id` (this delivery) · `idempotency_key`
  (logical step — stable across a hop's retries/redeliveries/replays) · `trace_id`
  (the transaction across hops; a replay starts a new trace linked via
  `replayed_from`). The Observatory ingestion contract was renamed in lockstep;
  its persistence reader still accepts the old `event_id` key for back-compat.

### Features

- Event/Transport abstraction (in progress): foundations for moving propagation
  and acknowledgement off transport-specific `Message` fields onto per-transport
  adapters (see `docs/otel-migration.md`).
  - OpenTelemetry propagation (`event/otel.py`): carrier inject/extract +
    producer/consumer spans + lost-context discontinuity flag + opt-in
    `configure_tracing`. `opentelemetry-api` is now a core dependency. **Wired into
    dispatch**: consumers expose `carrier()` (SQS→message attributes,
    webhook→HTTP headers); dispatch extracts via the carrier and runs a CONSUMER
    span; the emitter reads the live span context (envelope unchanged). This fixes
    the webhook trace break — propagation no longer depends on a transport-specific
    `Message` field. **Producers** wrap publish in a PRODUCER span and inject the
    active OTel context, so a handler that publishes downstream **continues the same
    trace across services** (multi-hop lineage now connects end to end).
  - Cleanup (Phase 4, done): the bespoke `event/tracing.py` (W3C `TraceContext` /
    `TraceContextPropagator` / `trace_scope` / `continue_trace` / `inject_current`)
    is **removed** — OTel is the sole trace plane; its lone surviving helper
    `coerce_header_value` moved into `event/otel.py`. The `metadata` field moved
    **off the base `Message`** (now a thin id + body + idempotency_key + timestamp)
    onto the inbound `ConsumerMessage` where broker delivery attributes actually
    belong (mirroring `WebhookMessage.headers`), so generic dispatch never reaches
    into a transport-specific base field.
  - `Acknowledger` (`event/acknowledgement.py`): every `EventConsumer` *is* an
    `Acknowledger` with broker-agnostic dispositions `ack` / `retry` / `dlq`
    (no `nack` — it conflated retry-or-dead-letter). Defaults are no-ops (push
    transports/webhook); `SQSConsumer` implements all three (delete / reset
    visibility / divert to DLQ). Dispatch is wired: success→ack, retryable→retry,
    non-retryable→dlq (single terminal telemetry status; `on_dead_letter` fires
    from the lifecycle). `use_acknowledger()` swaps the strategy (e.g. dead-letter
    to a store) independently of the ingress transport.
  - Replay causality (`event/otel.py` `replay_span` + DLQ redrive): a DLQ redrive
    starts its **own** trace (not grafted onto the dead original) with an OTel
    `Link` back to it plus `replayed_from.{trace_id,span_id}` span attributes, and
    propagates a `replayed_from` header (= original trace id) on the re-sent
    message. `SQSConsumer.dlq` now preserves the carrier as message attributes so
    the original trace survives the trip to the DLQ; `SQSDlqRedriver` flattens
    those attributes back into a carrier and emits the linked replay span. The
    emitter surfaces `replayed_from` on the `TelemetryEnvelope`, so the Observatory
    can show "replay of trace X" as a first-class link rather than a guess.
- Event/Tracing (A1): W3C trace-context propagation via `Message.metadata`.
  Producers inject the current trace on publish (SQS as message attributes, Redis
  via a wire envelope); consumers continue it as a child span across the dispatch
  lifecycle. New: `TraceContext`, `TraceContextPropagator`, `trace_scope`,
  `current_trace`, `continue_trace`, `inject_current`.
- Event/Telemetry (A2): `TelemetryDispatchHook` emits a `TelemetryEnvelope` at
  each dispatch outcome (complete→success, failure→failed, retry→retrying) to a
  pluggable `TelemetrySink` (`StdoutTelemetrySink`, `HttpTelemetrySink`,
  `ProducerTelemetrySink`, `NullTelemetrySink`). One-call wiring via
  `attach_telemetry(bus)` / `TelemetrySettings` (env prefix `MIDIL_TELEMETRY_`).
  Envelope matches the Midil Observatory ingestion contract.
- Event/Idempotency (A3): consumer-level deduplication applied at the dispatch
  boundary (`consumer.use_idempotency(IdempotencyPolicy(...))`), so it covers every
  subscriber type and never cross-blocks sibling subscribers. A duplicate delivery
  is acked and reported via the new `on_duplicate` dispatch hook (no message
  mutation). `IdempotencyStore` interface with `InMemoryIdempotencyStore` and
  `RedisIdempotencyStore` (atomic `SET NX EX`); the claim is released on
  retry/failure so redeliveries can re-process. The dedup key is a typed
  `Message.idempotency_key` (falling back to `Message.id`), not a metadata lookup.
- Event/DLQ (A4): `on_dead_letter` dispatch-hook stage (emitted by the SQS consumer
  when a message is moved to a DLQ) → `dlq` telemetry. `DlqRedriver` /
  `SQSDlqRedriver` primitive re-drives dead-lettered messages back to the source
  queue — the data-plane executor behind the Observatory's replay command.

### Fixed

- SQS: consumer config `region`/`dlq_region` used `ArnParser.parse` (which does not
  exist) instead of `parse_arn`, raising `AttributeError` on every SQS ack/nack.

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
