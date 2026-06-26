# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Features

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
