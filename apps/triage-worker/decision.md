# Architecture Decision Record (ADR): Triage Worker

Foundational decisions for the `triage-worker` — ingest-side dedupe, GPU routing, and DLQ escalation.

---

## 1. Chain-of-Responsibility Dedup Pipeline

**Decision:** Run handlers in order: exact SHA-256 Redis key (`doc:hash:…`), then a version-update stage that honors `metadata.is_version_update=true`.

**Alternatives Evaluated:**
* Exact hash only (misses near-duplicates / intentional revisions).
* Full content MinHash LSH in-process on every event.

**Why Chosen:** Exact hash cheaply drops byte-identical re-uploads and triggers S3 cleanup. The second stage keeps the pipeline extensible for richer similarity later while today’s producers can already flag version updates without re-extracting blindly as “new.” Trade-off: true fuzzy LSH is not computed here yet — only the chain seam and metadata path exist.

---

## 2. Bounded Goroutine Pool

**Decision:** Cap concurrent `processMessage` work with a semaphore sized by `APP_CONCURRENCY` (default 100).

**Why Chosen:** Kafka fetch is sequential; fan-out happens after fetch. Bounding concurrency protects Redis/Kafka producers under ingest spikes without unbounded goroutine growth.

---

## 3. Redis Fail-Count → DLQ (No Silent Drop)

**Decision:** On failure (including recovered panics), `INCR dlq:failcount:{eventId}`; after `APP_MAXRETRIES`, publish the original payload to `KAFKA_DLQTOPIC` and commit the ingest offset.

**Why Chosen:** Malformed protobuf or transient infra errors should not poison the partition forever, and should not vanish. Redis keeps retry state cheap across worker restarts within TTL of the key lifecycle.

---

## 4. Strategy Interface for Downstream Routing

**Decision:** Route accepted work through `RoutingStrategy` (currently `GpuRouteStrategy` → `KAFKA_GPUTOPIC`).

**Why Chosen:** Keeps the worker agnostic to future CPU/OCR lanes while tests mock a single `PublishMessage` surface.

---

## 5. Distroless Static Binary

**Decision:** Multi-stage `CGO_ENABLED=0` build to `gcr.io/distroless/static-debian11` (monorepo build context for `contracts` replace).

**Why Chosen:** No MuPDF/CGO in this service anymore — deps are pure Go. Distroless matches `api-gateway` / `s3-connector` and shrinks runtime attack surface.
