# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Breaking — event model re-architecture

- **A message is not an event.** The `Message` hierarchy (`Message`,
  `ConsumerMessage`, `WebhookMessage`), the `ObservedMessage` dataclass, the
  `MessageProtocol`, and the `Acknowledger` abstraction are **removed**,
  replaced by two clean concepts in `pymidil.event.core`:
  - **`Event`** — the immutable business fact, CloudEvents-shaped (`id` ·
    `source` · `type` · `data` · `subject` · `time` · `datacontenttype` ·
    `dataschema` · `extensions`), transport-free and serializable. `dedup_key`
    defaults to `id` (an explicit `idempotency_key` overrides).
  - **`Delivery`** — one transport attempt (a plain class, not a model — it
    holds a live ack handle). Owns the disposition (`ack`/`retry`/`dlq`) and
    `carrier()`; `SQSDelivery`/`WebhookDelivery`/`ObservedDelivery` are the
    concrete deliveries. `NoAckDelivery` is the no-settlement base for
    push/observed transports.
  Transport specifics (the SQS `{"StringValue"}` envelope, `ApproximateReceiveCount`,
  region-from-ARN) are now quarantined inside `SqsDelivery` — the rest of the
  SDK never peels a broker shape. The emitter reads `delivery.event.*` off
  typed fields (no more defensive `getattr`), and the zero-refactor observer
  builds a real `Event` + `ObservedDelivery`, so there is one message model,
  not two bridged by a partial protocol.
- **Handlers receive the `Event` — and nothing else.** The handler contract is
  one sentence: `async def handle(self, event)`; what it returns or raises
  decides the delivery's fate (return → ack, `RetryableEventError` → retry,
  any other exception → dead-letter). There is no context parameter: an
  adversarial design review found no surveyed framework passes a
  zero-capability context (GCF gen2 deleted exactly that shape), attempt-count
  idiomatically lives in broker/dispatcher policy (SQS `maxReceiveCount`
  redrive; a dispatcher `max_attempts` is roadmapped) and in telemetry
  (`envelope.attempts`), and per-handler give-up logic is incoherent under
  fan-out aggregation anyway (a sibling's retry request overrides it).
- **Producers publish an `Event` natively.** `publish(event)` replaces
  `publish(payload, event_type=…, idempotency_key=…)`: the event's `data`
  becomes the message body and its CloudEvents attributes (`id`, `source`,
  `type`, `subject`, `time`, `idempotency_key`, `ext_*`) ride the transport's
  attribute side-channel — CloudEvents *binary content mode*. The one place
  that mapping is defined is `pymidil.event.wire` (`event_to_wire` /
  `wire_to_event`), so a consumer reconstructs the same `Event` on the other
  side, and a foreign producer that didn't stamp the attributes still yields a
  valid `Event` via the transport's own id/timestamp fallbacks. The transport
  seam matches: `_publish(event)` (was `_publish(payload, metadata)`) — each
  transport frames the event for its own wire (SQS side-channels the attributes
  into `MessageAttributes`, Redis inlines them), symmetric with the consumer's
  per-transport `wire_to_event`. The vestigial `**kwargs` on `publish`/`_publish`
  is removed. `EventBus.publish` (a dead, unbuilt convenience) is removed.

### Features

- **The bus is the platform — observability is built in.** `EventBus` is now
  observed by default: it resolves the Observatory connection contract
  (`MIDIL_OBSERVATORY_URL` / `MIDIL_API_KEY` / `MIDIL_SERVICE`, via the new
  `ObservabilityConfig`) at construction and instruments every producer and
  consumer it builds or that you register — zero telemetry wiring. Turn it off
  with `EventBus(observability=False)` or pass an explicit `ObservabilityConfig`.
  The API key lives only inside the bus's telemetry sink, never on a transport
  config. Raw components built outside a bus stay pure (no import- or
  construction-time telemetry side effects), so unit tests never emit by
  accident.
- **`bus.include_consumer(name, instance, *, service=None)` /
  `include_producer(...)`** — register pre-built, hand-assembled components
  (custom sessions, injected dependencies) alongside config-built ones through
  one registration funnel, where instrumentation is applied uniformly.
  `service` overrides attribution for a process running several logical services.
- **`bus.run()`** — the paved-road worker entrypoint: start all consumers, wait
  on SIGINT/SIGTERM, shut down cleanly (consumers, producers, telemetry sink).
- **`consumer.use_idempotency()`** now takes no arguments for the common case —
  an in-memory store keyed on the delivery's `event.dedup_key` (the
  `idempotency_key` when present, else the event `id`), which round-trips
  through the wire attributes so it survives redelivery.

### Improvements

- A missing `MIDIL__EVENT` no longer errors: a bus populated entirely through
  `include_*` is first-class, so declarative config is optional (empty bus,
  logged as a warning).
- **One message model, one wire contract, one home.** The seam that used to
  drift — a `MessageProtocol` declaring only `id` while the emitter read five
  fields, two message types conforming by accident — is gone by construction:
  there is a single `Event` model, and the producer/consumer boundary is the
  single `pymidil.event.wire` mapping. `pymidil/event/message.py` (a file named
  after the deleted `Message` concept) is removed; its wire attribute-name
  constants now live in `wire.py` beside the mapping that is their only
  consumer, and the `MessageBody` payload alias retires with the old
  `_publish(payload, …)` seam.
- **Retry policy: bounded by default, declared fates, no silent fallbacks.**
  Pull consumers carry a `RetryConfig` (`max_attempts=5`, jittered 5→300s
  exponential backoff; `max_attempts=None` is the explicit unbounded opt-in
  for consumers that legitimately wait on out-of-order events). The dispatcher
  DECIDES — it bounds the budget (`retry budget exhausted after N attempts`)
  and computes each delay — and the transport ENACTS (`delivery.retry(delay)`;
  SQS via visibility timeout). An SQS consumer must DECLARE its terminal fate:
  `dlq_url` XOR `no_dlq="requeue"|"drop"` — construction refuses otherwise
  with a teaching message; the silent no-DLQ fallback (infinite redelivery
  reported as DLQ) is deleted. Terminal failures route by the declared fate
  with telemetry that matches the physical action (requeue reports RETRYING,
  never a fake DLQ). Policies are validated against `TransportCapabilities`
  at construction — a bounded budget on a transport that cannot count
  attempts refuses loudly instead of silently never triggering. The SQS
  `backoff_base_delay`/`backoff_max_delay` config fields are absorbed into
  `retry.*`. Note: SQS attempt counting is `ApproximateReceiveCount` — a
  ceiling on *deliveries*, not handler runs; a queue redrive `maxReceiveCount`
  lower than `max_attempts` diverts broker-side first.
- **DX hardening (from a blind A/B audit of the SDK).** (1) *No silent queue
  draining*: a consumer with zero subscribers no longer ACKS (deletes)
  deliveries — they stay unsettled for redelivery with an ERROR log, and
  `start()` warns when a consumer boots subscriber-less. (2) *No ambient
  surprises*: `EventBus` now logs every consumer/producer it absorbs from
  declarative config (`MIDIL__EVENT` / a `.env` in cwd), and
  `bus.subscribe()` refuses to guess when multiple consumers are registered —
  pass `target=` explicitly. (3) *Base install works*: `import pymidil` and
  `import pymidil.event` no longer require optional dependencies — the root
  and event barrels are lazy (PEP 562), and a missing extra raises an
  ImportError naming the extra to install (`pip install 'pymidil[aws]'`).
  (4) *Papercuts*: `Event.id` is auto-minted (uuid4) when not supplied;
  `HttpTelemetrySink` is exported from `pymidil.event.observability`; the SQS
  poll loop now survives broker outages indefinitely (backed-off retry)
  instead of dying after 3 consecutive errors; the env-var convention is
  documented (single underscore = flat contract vars, double = nested config).
  (5) *Pruned*: the vestigial `EventContext` contextvar module (superseded by
  the OTel plane), the `pymidil.event.exceptions` re-export shim (event errors
  live at `pymidil.exceptions`), and `RetryMiddleware` (in-process retries
  fight the transport retry plane) are deleted. (6) *Layout*: transports moved
  under the domain that owns them — `pymidil.event.transports.<name>` — so the
  event platform is one package, not two.
- **The WebSocket transport is removed** (`transports/websocket/`). It failed
  both tests of the transport doctrine: no architectural role (services event
  through brokers; third parties through webhooks; realtime UI belongs to the
  console↔API side, not the SDK) and no settlement contract (a frame has no
  per-message response channel, so a failed delivery has no honest disposition
  — a transport that structurally cannot report truth contradicts the
  product's core promise). It was also unreachable through the platform
  (never registered in the bus factory or declarative config), off the wire
  contract, and consumed by nothing. Webhook stays: foreign-producer ingress
  with a real sender-mediated settlement contract (HTTP status = disposition).
- **The DLQ redriver is removed** (`pymidil/event/dlq/`, `SQSDlqRedriver`,
  `otel.replay_span`). It was speculative surface for the replay feature the
  console lists as coming-soon — nothing imported it outside its own test —
  and it carried a confirmed defect: replaying dropped the original wire
  attributes, so a redriven message came back with a new id, `type="unknown"`,
  and reset dedup identity. When replay ships, the reimplementation must
  forward the original producer-namespace attributes (identity + trace) and
  only add/refresh `replayed_from`; the `replayed_from` wire/envelope contract
  stays in place for it. Dead-lettering itself (the divert side: declared
  fates, `SQSSettlement.dlq`, DLQ telemetry) is unaffected.
- **Dispatch failures are contained, never escalated blind.** A
  dispatcher-level error (idempotency-store outage, malformed wire) no longer
  hard-dead-letters the message — the outcome is unknown, so the message is
  left unsettled for redelivery — and no longer aborts the batch: one bad
  message cannot cancel sibling dispatches mid-handler (burning their retry
  budgets) or silently kill the poll loop. A poll-loop death is now recorded
  observably (`_running=False` + critical log) instead of a swallowed raise in
  a done-callback. SQS system attributes and producer message attributes are
  separate namespaces end-to-end: producers can no longer shadow
  `ApproximateReceiveCount`/`SentTimestamp`, and a DLQ divert forwards only
  the producer namespace (identity + trace), never stale broker counters.
  Config coherence: `no_dlq="requeue"` with a finite `max_attempts` is refused
  (the budget could terminate nothing); stale config keys now fail loudly
  (`extra="forbid"`); the exhaustion reason ("retry budget exhausted after N
  attempts") reaches telemetry envelopes; exponential backoff no longer
  overflows at high attempt counts on unbounded consumers, and jitter can no
  longer exceed the configured cap.
- **Transports live under `pymidil.transports.<name>`.** ALL transports moved
  out of `event/`: `transports/{sqs,redis,webhook,websocket}/` (transport-first
  packaging, MassTransit/NServiceBus vocabulary — *transports*, not *brokers*,
  because push ingress is a transport but not a broker; adding one touches one
  new package). `event/` keeps only the framework layer (core model, wire,
  dispatch strategies, producer base, bus, observability). `WebSocketPush*`
  classes renamed `WebSocket*` for sibling consistency. Inside SQS,
  the roles split: `SQSDelivery` *reads* the wire (identity, attempt count,
  trace carrier) and owns the settle-once latch; `SQSSettlement` *writes* (the
  physical broker calls). `Settlement` is the new core seam — named for the
  industry vocabulary (AMQP's *disposition* is the settlement outcome/state,
  which `Delivery.disposition` records; the executor is the settlement).
  Casing standardized (`SQSDelivery`); `Event` gains CloudEvents `specversion`.
  The model has exactly ONE abstract write contract: `Settlement` owns the
  physical verbs AND the declared terminal fate; `Delivery` is CONCRETE —
  identity, reads, and the settle-once latch, composing a `Settlement`
  (default `NoSettlement`: no-op writes, truthful `drop` fate). Transport
  delivery subclasses exist only for genuinely transport-specific READS;
  the `_ack/_retry/_dlq` template-method layer is deleted. Test doubles
  compose recording settlements — the same seam real transports use.
- **The dispatcher owns settlement — exclusively.** Handlers never see the
  `Delivery` (there is no context object at all — see the handler-contract
  bullet above): one delivery fans out to many concurrent subscribers, so its
  disposition is an aggregation of every subscriber's outcome — no single
  handler may settle it, and settlement routed around the dispatcher bypassed
  telemetry (a manually dead-lettered message was recorded as SUCCESS).
  Handlers drive the outcome by what they return or raise — the Lambda model,
  and the only settlement-authority shape any surveyed multi-listener
  framework uses. Future handler-facing capabilities, if ever needed, must be
  non-settling and injected as bound operations, never as the delivery.
- **A delivery settles exactly once.** `Delivery`'s public `ack()/retry()/dlq()`
  are now first-disposition-wins latches (a later disposition is refused with
  an error log, never applied — one physical disposition per attempt); the
  `disposition`/`settled` properties expose what happened. Transports implement
  the physical operations in `_ack()/_retry()/_dlq()` and may compose those
  primitives (SQS dead-lettering sends to the DLQ then deletes from source).
  This guards every dispatcher settlement path against double-dispatch bugs
  (Watermill/Kombu precedent).
- **Handler invocation is plain.** With one handler shape there is nothing to
  classify: `EventSubscriber.__call__` awaits `self.handle(event)` directly,
  and `FunctionSubscriber` normalizes its sync-or-async leaf in one place
  (`inspect.isawaitable`, so futures and custom awaitables work too). The
  signature-inspection machinery (`invocation.py`) is deleted with the opt-in
  it existed to serve. A trap for any future re-introduction, learned the hard
  way: never cache signature classifications by code object —
  `functools.wraps` wrappers from one decorator share a single code object
  while `inspect.signature` follows `__wrapped__`, so the first handler
  inspected poisons the rest. `_execute_subscribers` snapshots the subscriber
  set so a concurrent `subscribe()` mid-dispatch can no longer mispair
  results.
- **Producer telemetry reads the typed `Event`, symmetric with the consumer.**
  `PublishRecord` now carries the `Event`, so `TelemetryProducerHook` reads
  `event.type` / `event.time` / `event.dedup_key` / `event.extensions` off typed
  fields instead of string-re-parsing a wire dict and fabricating a timestamp —
  the same shape `TelemetryDispatchHook` reads off `delivery.event`. Publish
  timing + hook notification are hoisted into the `EventProducer` template, so
  the Redis producer now emits producer telemetry too (it previously emitted
  none), and both transports settle observability through one path.

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
