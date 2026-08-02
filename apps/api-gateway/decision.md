# Architecture Decision Record (ADR): API Gateway

Foundational decisions for the `api-gateway` service — streaming ingress, statelessness, and async handoff to the document pipeline.

---

## 1. Streaming Uploads over Buffered Uploads

**Decision:** Stream multipart parts directly to S3 with AWS SDK v2 `transfermanager`, hashing via `io.TeeReader` (SHA-256) on the fly.

**Alternatives Evaluated:**
* Buffer the full file in RAM, then upload.
* Spool to container disk, hash, then upload.

**Why Chosen:** Keeps memory near-constant for multi-GB PDFs and concurrent uploads. Trade-off: the final hash is only known after the upload finishes, so pre-upload duplicate rejection cannot happen in the gateway alone.

---

## 2. Stateless Architecture (No Postgres / Redis)

**Decision:** The gateway talks only to S3 and Kafka. Deduplication and job state live in downstream workers (`s3-connector` / Postgres).

**Alternatives Evaluated:**
* Check file hashes in Redis/Postgres before returning 202.
* Client-side preflight hash check (Dropbox-style).

**Why Chosen:** Stateless replicas scale behind an HPA without shared mutable state. Duplicate uploads are accepted at the edge and dropped or merged asynchronously where durable state already exists.

---

## 3. Asynchronous Event-Driven Handoff (Kafka)

**Decision:** After S3 put + protobuf `IngestEvent` publish, return `202 Accepted`. Status updates go to `document_status_events`.

**Alternatives Evaluated:**
* Synchronous HTTP/gRPC to GPU / aligner workers.
* Redis Pub/Sub or RabbitMQ.

**Why Chosen:** Extraction is slow and bursty. Kafka buffers spikes, retains events for replay, and lets independent consumer groups fan out. Clients learn final status via SSE/polling elsewhere in the stack.

---

## 4. Local S3: Adobe S3Mock

**Decision:** Local stack uses Adobe S3Mock (+ init sidecar for `prism-raw-documents`) instead of LocalStack or MinIO.

**Why Chosen:** Free, fast S3 API emulation without LocalStack Pro restrictions or MinIO’s heavier ops/license profile. Trade-off: S3-only — other AWS APIs would need additional mocks.

---

## 5. Telemetry via OTEL Collector

**Decision:** Export OTLP traces to an in-compose `otel-collector`, which batches to Grafana Tempo.

**Why Chosen:** Matches production collector patterns, offloads retry/batch from the gateway process, and avoids vendor lock-in. Trade-off: one extra local container and hop.

---

## 6. Kafka Topic Auto-Creation (Local)

**Decision:** `AllowAutoTopicCreation: true` on the kafka-go writer for local compose.

**Why Chosen:** Blank local clusters get `doc_ingest_events` / status topics on first publish without an init job. Production should pre-provision topics with fixed partitions/replication (disable auto-create there).

---

## 7. Distroless Runtime Image

**Decision:** Multi-stage build ending in `gcr.io/distroless/static-debian11`.

**Why Chosen:** Minimal attack surface and image size for a static Go binary. Trade-off: no shell in the container for live debugging (`docker exec`).

---

## 8. No Gateway-Side Idempotency Locks

**Decision:** Do not take Redis locks or idempotency keys on upload.

**Why Chosen:** Preserves Decision #2. Aggressive client retries may emit duplicate Kafka events; workers with Postgres/Redis ownership handle dedupe. Edge rate limiting belongs on Nginx / cloud API Gateway if needed later.

---

## 9. Collision-Safe S3 Object Keys

**Decision:** Key shape `tenantID/unix-shortUUID-filename`.

**Why Chosen:** Streaming means the content hash is unavailable for the key. Timestamp + filename alone can collide under concurrent same-name uploads in the same second; a short UUID removes overwrite races.
