# Architecture Decision Records (umbrella)

Cross-cutting ADRs for Prism Core. **Service-local truth** lives in `apps/*/decision.md` and [`infra/decision.md`](infra/decision.md) — prefer those when they disagree with older bullets here.

Grouped by pipeline stage: ingestion → vision → alignment → sync → agents.

---

## Part 1: Ingestion & routing (Go)

### 1.1 Zero-copy streaming ingress
**Service:** `api-gateway`  
**Decision:** Stream multipart uploads to S3 with `mime/multipart.Reader`; publish protobuf `IngestEvent` after object land.  
**Rejected:** `ReadAll` into RAM (OOM on large PDFs).  
**See:** `apps/api-gateway/decision.md`

### 1.2 Dedup chain before GPU
**Service:** `triage-worker`  
**Decision:** Chain-of-responsibility: exact SHA-256 Redis key, then version-update metadata path; DLQ after Redis fail-count.  
**Note:** Full MinHash LSH is aspirational — today’s second stage honors `is_version_update` metadata.  
**See:** `apps/triage-worker/decision.md`

### 1.3 SQS buffer → Kafka
**Services:** `sqs-kafka-bridge`, `s3-connector`  
**Decision:** AWS notifications → SQS/ElasticMQ → Kafka discovery → connector dedupe → gateway upload.  
**See:** `apps/sqs-kafka-bridge/decision.md`, `apps/s3-connector/decision.md`

---

## Part 2: Vision & layout (GPU)

### 2.1 Element-level routing
**Service:** `gpu-extractor`  
**Decision:** Layout boxes (RT-DETR / Docling Heron class) route per element (text cheap path vs table/KV VLM), not whole-document monolithic VLM.  
**See:** `apps/gpu-extractor/decision.md`

### 2.2 Reading order (1D cluster + X sort)
**Service:** `gpu-extractor`  
**Decision:** Geometric Y-clustering + X-sort for multi-column pages instead of naive PDF scrape order.  
**See:** `apps/gpu-extractor/decision.md`

---

## Part 3: Alignment & verification

### 3.1 Structured outputs, not in-process outlines
**Service:** `schema-aligner`  
**Decision:** Dynamic Pydantic models from `registry.json` + instructor / OpenAI-compatible structured decode (vLLM optional).  
**Rejected:** Free-form JSON + retry soup; tying workers to local `outlines` logit masking.  
**See:** `apps/schema-aligner/decision.md`

### 3.2 Critics + Reflexion before HITL
**Service:** `schema-aligner`  
**Decision:** Declarative critic packs emit structured `CriticResult`; bounded Reflexion repair; then DLQ/HITL.  
**See:** `apps/schema-aligner/decision.md`

### 3.3 Context fields injected, not copied into every schema
**Service:** `schema-aligner`  
**Decision:** Inject `context_*` (entity, period, currency, scale) at compile time from bifurcation context.  
**Rejected:** Duplicating those keys in every registry table.  
**See:** `apps/schema-aligner/decision.md`

---

## Part 4: Storage & CDC

### 4.1 Hybrid JSONB rows + upserts
**Service:** `storage-sync`  
**Decision:** `extracted_tables` with `strict_columns` JSONB; `ON CONFLICT (document_id, node_id, row_index)`.  
**See:** `apps/storage-sync/decision.md`

### 4.2 Eventual consistency over multi-write
**Service:** `storage-sync`  
**Decision:** Kafka-driven sync + optional Debezium observer; Postgres first, vectors/graph catch up.  
**Rejected:** Distributed transactions across PG/Neo4j/Qdrant from the aligner.  
**See:** `apps/storage-sync/decision.md`, `infra/decision.md`

### 4.3 Registry → SQL views → Cube
**Services:** `storage-sync`, `infra/cube`  
**Decision:** Generate `view_*` from registry; Cube YAML generated from the same registry with tenant filter rewrite.  
**See:** `apps/storage-sync/decision.md`, `infra/decision.md`

---

## Part 5: Agentic layer & UI

### 5.1 Deterministic task registry
**Service:** `agentic-brain`  
**Decision:** `/task` uses an explicit agent registry (not LLM-authored code execution / Celery).  
**See:** `apps/agentic-brain/decision.md`

### 5.2 LangGraph for chat routing
**Service:** `agentic-brain`  
**Decision:** Supervisor routes SQL / Cypher / vector tools under a typed graph state.  
**See:** `apps/agentic-brain/decision.md`

### 5.3 Dual public URLs for the UI
**Service:** `web-dashboard`  
**Decision:** `NEXT_PUBLIC_API_URL` (brain) + `NEXT_PUBLIC_GATEWAY_URL` (uploads), baked at Docker build.  
**See:** `apps/web-dashboard/decision.md`

---

## Part 6: Future horizons

1. **HITL → distillation** — patch deltas as LoRA data for smaller constrained models.  
2. **Neo4j native vectors** — optional Qdrant consolidation for hybrid GraphRAG.  
3. **KEDA on Kafka lag** — scale GPU workers to zero when idle.  
4. **S3 byte-range fan-out** — faster ingest for multi-GB objects in Go.
