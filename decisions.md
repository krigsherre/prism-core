# Architecture Decision Records (umbrella)

Cross-cutting ADRs for Prism Core. **Service-local truth** lives in `apps/*/decision.md` and [`infra/decision.md`](infra/decision.md) — prefer those when they disagree with older bullets here.

For full system diagrams and pipeline specs, see [`architecture.md`](architecture.md).

Grouped by pipeline stage: ingestion → vision → alignment → sync → agents → horizontal scalability.

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

### 1.4 Dual Ingestion & Structured Fast-Path Routing
**Service:** `schema-aligner`  
**Decision:** Inspect incoming document types via `doc_router`. Structured digital filings (SEC iXBRL HTML or Indian MCA/BSE XBRL XML) bypass VLM rendering entirely and parse embedded taxonomy tags directly into canonical JSON with near 100% precision. Unstructured PDFs/images route to `gpu-extractor`.  
**See:** `apps/schema-aligner/decision.md`

---

## Part 2: Vision & layout (GPU)

### 2.1 Element-level routing
**Service:** `gpu-extractor`  
**Decision:** Layout boxes (RT-DETR / Docling classes) route per element (text cheap path vs table/KV VLM), not whole-document monolithic VLM.  
**See:** `apps/gpu-extractor/decision.md`

### 2.2 Reading order (1D cluster + X sort)
**Service:** `gpu-extractor`  
**Decision:** Geometric Y-clustering ($\varepsilon \approx 15\text{px}$) + X-sort for multi-column pages instead of naive PDF scrape order.  
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
**Decision:** Declarative critic packs emit structured `CriticResult`; bounded Reflexion repair loop feeds equation errors back into prompt; then DLQ/HITL.  
**See:** `apps/schema-aligner/decision.md`

### 3.3 Context fields injected, not copied into every schema
**Service:** `schema-aligner`  
**Decision:** Inject `context_*` (entity, period, currency, scale) at compile time from bifurcation context.  
**Rejected:** Duplicating those keys in every registry table.  
**See:** `apps/schema-aligner/decision.md`

### 3.4 Row-Oriented Chunking over Columnar Parallel Arrays
**Service:** `schema-aligner`  
**Decision:** Extract large financial tables in small row chunks (default 10 rows) as typed Pydantic objects, then merge in Python.  
**Rejected:** Columnar parallel arrays (which suffer column-length index drift) or single-prompt whole-table generation.  
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

### 4.4 Graph Triple Ingestion via Pre-Filtering & UNWIND Batching
**Services:** `storage-sync`, `agentic-brain`  
**Decision:** Pre-filter text nodes for strategic financial keywords before dispatching to Kafka; ingest triples via single-transaction Neo4j `UNWIND` batches.  
**See:** `apps/storage-sync/decision.md`, `apps/agentic-brain/decision.md`

---

## Part 5: Agentic layer & UI

### 5.1 Deterministic task registry
**Service:** `agentic-brain`  
**Decision:** `/task` uses an explicit agent registry (not LLM-authored code execution / Celery).  
**See:** `apps/agentic-brain/decision.md`

### 5.2 LangGraph for chat routing & Zero-Latency Fast-Paths
**Service:** `agentic-brain`  
**Decision:** Parallel fan-out to SQL / Cypher / Vector under a typed graph state with sub-$1\text{ms}$ sub-agent fast-paths for non-analytical queries.  
**See:** `apps/agentic-brain/decision.md`

### 5.3 Local Neural Embedding & Reranking via TEI Sidecars
**Service:** `agentic-brain`  
**Decision:** Decouple dense vector embedding (`bge-small-en-v1.5`) and cross-encoder reranking (`bge-reranker-base`) into specialized HuggingFace TEI microservices (`:8085` and `:8086`), preventing Python GIL bottlenecks during hybrid RAG.  
**See:** `apps/agentic-brain/decision.md`

### 5.4 Real-Time HITL Escalation & SSE Event Streaming
**Services:** `schema-aligner`, `web-dashboard`  
**Decision:** Critic failure DLQ events are pushed via Server-Sent Events (SSE) directly to the web dashboard, providing operators with a real-time HITL review queue without polling.  
**See:** `apps/web-dashboard/decision.md`, `apps/schema-aligner/decision.md`

### 5.5 Tool-Side Multitenancy & Query Rewriting
**Service:** `agentic-brain`  
**Decision:** Multi-tenancy isolation (`tenant_id`) is strictly enforced at the database driver/tool wrapper layer (`postgres_tools`, `neo4j_tools` AST rewriting, Qdrant payload filters) — never relying on prompt instructions.  
**Rejected:** Asking the LLM to remember `WHERE tenant_id = …` in prompt strings.  
**See:** `apps/agentic-brain/decision.md`

### 5.6 HITL Correction Distillation Loop
**Services:** `web-dashboard`, `schema-aligner`  
**Decision:** Human corrections approved in HITL are saved as structured JSON patch deltas and exported (`scripts/export_corrections.py`) to build fine-tuning goldens for smaller extraction models.  
**See:** `apps/web-dashboard/decision.md`, `apps/schema-aligner/decision.md`

### 5.7 Domain-Agnostic Engine Design (SEC 10-K & Financials as Primary Target)
**Services:** `schema-aligner`, `storage-sync`, `agentic-brain`  
**Decision:** Financial 10-K / SEC filings serve as the primary high-complexity target domain (demanding relational SQL, prose vectors, and corporate graphs simultaneously). The pipeline, schema aligner registry, and tri-modal RAG architecture are 100% domain-agnostic and extendable to Healthcare, Legal, and Insurance domains by swapping registry schemas and graph prompts.  
**See:** `apps/schema-aligner/decision.md`, `apps/agentic-brain/decision.md`

---

## Part 6: Horizontal Scalability & Distributed Architecture

### 6.1 Partition-Keyed Consumer Group Scaling
**Services:** `triage-worker`, `gpu-extractor`, `schema-aligner`, `storage-sync`  
**Decision:** All compute-intensive processing runs as stateless Kafka consumer groups keyed by `document_id` / `tenant_id`. Scaling throughput is achieved by adding Kafka topic partitions and launching additional worker container replicas (`docker-compose up --scale gpu-extractor=4 --scale schema-aligner=8`) without code modifications.  
**Rejected:** In-process threading queues or tightly-coupled synchronous HTTP chain calls between workers.  
**See:** `apps/gpu-extractor/decision.md`, `apps/schema-aligner/decision.md`

### 6.2 Centralized Model Inference Sidecars
**Services:** `gpu-extractor`, `schema-aligner`, `agentic-brain`  
**Decision:** Decouple heavy neural models (vLLM, PaddleOCR-VL, HuggingFace TEI) into dedicated, centralized HTTP/gRPC inference servers (`:8004`, `:8085`, `:8086`). Worker replicas make lightweight async HTTP calls to shared inference endpoints.  
**Rejected:** Loading 7B model weights directly inside each worker process (which multiplies VRAM usage by replica count).  
**Why Chosen:** Worker replicas scale horizontally on cheap CPU instances, while GPU resources scale independently behind centralized vLLM/TEI endpoints guarded by worker-side `asyncio.Semaphore` rate limits.  
**See:** `apps/gpu-extractor/decision.md`, `apps/agentic-brain/decision.md`

### 6.3 Stateless Task Claiming via `FOR UPDATE SKIP LOCKED`
**Service:** `agentic-brain`  
**Decision:** Background task workers claim pending jobs directly from Postgres using `SELECT ... FOR UPDATE SKIP LOCKED`.  
**Rejected:** Distributed Redis lock management or Celery/RQ infrastructure overhead.  
**Why Chosen:** Allows N worker replicas of `agentic-brain` to poll the task queue concurrently without lock contention, double-claiming, or deadlocks.  
**See:** `apps/agentic-brain/decision.md`

### 6.4 Atomic Upsert Keys for Safe Re-Balancing
**Service:** `storage-sync`  
**Decision:** Postgres writes enforce composite natural keys `(document_id, node_id, row_index)` on conflict upsert. Qdrant vectors use deterministic UUIDv5 generated from `(document_id, node_id)`.  
**Why Chosen:** Guaranteed idempotency across Kafka partition re-balances, network retries, or worker crashes—preventing duplicate rows or vector pollution.  
**See:** `apps/storage-sync/decision.md`

---

## Part 7: Future horizons

1. **HITL → distillation** — patch deltas as LoRA data for smaller constrained models.  
2. **Neo4j native vectors** — optional Qdrant consolidation for hybrid GraphRAG.  
3. **KEDA on Kafka lag** — auto-scale worker container replicas dynamically based on Kafka consumer lag metrics.  
4. **S3 byte-range fan-out** — faster ingest for multi-GB objects in Go via parallel range requests.
