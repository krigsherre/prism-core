# Architecture Decision Record (ADR): S3 Connector

Foundational decisions for the `s3-connector` worker — batch Kafka ingest, exactly-once-ish dedupe, and routing through the API gateway.

---

## 1. Two-Tier Deduplication (Redis + Postgres)

**Decision:** Filter recent etags via Redis, then batch-check unknowns in Postgres (`SELECT … = ANY($1)`).

**Alternatives Evaluated:**
* Postgres-only lookups per event.
* Redis-only (no durable truth).

**Why Chosen:** Batches of hundreds of Kafka messages would hammer Postgres if checked one-by-one. Redis absorbs hot duplicates; Postgres remains the durable record. Trade-off: if Redis dies, traffic falls through to Postgres.

---

## 2. Distributed Lock via Redis SETNX

**Decision:** Acquire a per-etag processing lock with atomic `SETNX` (+ TTL) before streaming.

**Why Chosen:** Concurrent replicas can both observe a cache miss (TOCTOU). SETNX ensures only one worker processes a given etag. Trade-off: a crash after lock acquisition blocks retries until TTL (default 5m).

---

## 3. Kafka Batch Fetch

**Decision:** Fetch up to `APP_MAXBATCHSIZE` messages (default 500) or until `APP_FETCHTIMEOUT` before processing.

**Why Chosen:** One Redis pipeline + one Postgres query per batch beats per-message round trips. Trade-off: higher per-worker memory while buffering.

---

## 4. Distroless Runtime Image

**Decision:** Multi-stage build to `gcr.io/distroless/static-debian11`.

**Why Chosen:** Minimal attack surface for a static Go binary (same pattern as `api-gateway`). Trade-off: no shell for live container debugging.

---

## 5. Route Bytes Through API Gateway

**Decision:** Stream the external S3 object into `api-gateway` as multipart upload; do not publish `IngestEvent` directly from this worker.

**Why Chosen:** Keeps hashing, internal S3 layout, telemetry, and future validation in one ingress path. Trade-off: extra hop (external S3 → connector → gateway → internal S3).

---

## 6. OpenTelemetry Traces

**Decision:** OTLP export through the compose `otel-collector` for the batch lifecycle (fetch → lock → DB → gateway POST).

**Why Chosen:** Async multi-service flows need shared trace IDs; Zap logs alone do not stitch Kafka → HTTP hops.

---

## 7. Ingress Buffer (SQS → Kafka Bridge)

**Decision:** S3 notifications land in SQS; `sqs-kafka-bridge` forwards to Kafka; this service only consumes Kafka.

**Why Chosen:** SQS absorbs AWS-side spikes and outages; Kafka enables fan-out to future consumers. Reading SQS directly from `s3-connector` would steal messages and block that fan-out.
