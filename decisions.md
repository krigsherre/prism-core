<p align="center">
  <img src="apps/web-dashboard/app/icon.png" alt="Prism Core" width="72" />
</p>

<h1 align="center">Architecture Decision Records</h1>

<p align="center">
  Cross-cutting ADRs for Prism Core. Service-local truth lives in <code>apps/*/decision.md</code>.
</p>

<p align="center">
  <a href="README.md">🏠 README</a> ·
  <a href="architecture.md">📐 Architecture</a> ·
  <a href="research.md">📚 Research</a> ·
  <a href="infra/README.md">🔧 Infra</a>
</p>

---

## 🎯 Problem Framing & Project Scope

> **Problem Statement #3:** *Turn messy documents into structured, queryable data.*

### 1. Target Audience & Product Thinking
**Prism Core** solves the multi-page financial filing extraction problem for **financial analysts, auditors, and enterprise data engineers**. Messy financial PDFs (10-K filings, balance sheets, income statements, receipts, bank statements) contain complex multi-column reading orders, mixed text/table regions, and strict mathematical constraints (e.g. $\text{Assets} = \text{Liabilities} + \text{Equity}$).

Rather than building a generic naive PDF text-scraper, Prism Core turns unstructured documents into a **tri-modal queryable data system**:
1. **Structured SQL Tables** (PostgreSQL `JSONB` rows for precise columnar queries and financial ratio analytics).
2. **Dense Vector Index** (Qdrant `bge-small-en-v1.5` embeddings for semantic chunk retrieval).
3. **Knowledge Graph** (Neo4j entity triples for auditing corporate relationships, subsidiaries, and directors).

### 2. What We Deliberately Cut & Why
To deliver deep engineering quality within the project timeline, we made explicit scoping decisions:
* **Cut Monolithic VLM Rendering:** Avoided passing entire 100-page PDFs through 7B VLMs. Instead, element-level layout detection routes text to PyMuPDF and reserves VLM compute strictly for complex tables (reduced GPU cost by 80%).
* **Cut Prompt-Based Multi-Tenancy:** Rejected asking LLMs to append `WHERE tenant_id = ...` in prompt strings. Implemented AST query rewriting at the tool driver layer so isolation is hard-coded and injection-proof.
* **Deferred Full MinHash LSH:** Chained exact SHA-256 Redis deduplication and version metadata update paths first, deferring full fuzzy MinHash matrix calculations to post-v1.
* **Deferred LoRA Fine-Tuning Pipeline:** Captured human corrections in the HITL dashboard as structured JSON patch deltas (`scripts/export_corrections.py`), leaving active fine-tuning model compilation as a roadmap step.

---

## Decision Index

| # | Decision | Stage | Status |
|---|---|---|---|
| 1.1 | [Zero-copy streaming ingress](#11-zero-copy-streaming-ingress) | Ingestion | ✅ Implemented |
| 1.2 | [Dedup chain before GPU](#12-dedup-chain-before-gpu) | Ingestion | ✅ Implemented |
| 1.3 | [SQS buffer → Kafka](#13-sqs-buffer--kafka) | Ingestion | ✅ Implemented |
| 1.4 | [Dual ingestion & fast-path routing](#14-dual-ingestion--structured-fast-path-routing) | Ingestion | ✅ Implemented |
| 1.5 | [Protobuf v3 & Buf codegen stubs](#15-protobuf-v3--buf-codegen-stubs) | Contracts | ✅ Implemented |
| 2.1 | [Element-level routing](#21-element-level-routing) | Vision | ✅ Implemented |
| 2.2 | [Reading order — 1D cluster + X sort](#22-reading-order-1d-cluster--x-sort) | Vision | ✅ Implemented |
| 3.1 | [Structured outputs, not in-process outlines](#31-structured-outputs-not-in-process-outlines) | Alignment | ✅ Implemented |
| 3.2 | [Critics + Reflexion before HITL](#32-critics--reflexion-before-hitl) | Alignment | ✅ Implemented |
| 3.3 | [Context fields injected, not copied](#33-context-fields-injected-not-copied) | Alignment | ✅ Implemented |
| 3.4 | [Row-oriented chunking](#34-row-oriented-chunking-over-columnar-parallel-arrays) | Alignment | ✅ Implemented |
| 4.1 | [Hybrid JSONB rows + upserts](#41-hybrid-jsonb-rows--upserts) | Storage | ✅ Implemented |
| 4.2 | [Eventual consistency over multi-write](#42-eventual-consistency-over-multi-write) | Storage | ✅ Implemented |
| 4.3 | [Registry → SQL views → Cube](#43-registry--sql-views--cube) | Storage | ✅ Implemented |
| 4.4 | [Graph triple ingestion via pre-filtering](#44-graph-triple-ingestion-via-pre-filtering--unwind-batching) | Storage | ✅ Implemented |
| 5.1 | [Deterministic task registry](#51-deterministic-task-registry) | Agents | ✅ Implemented |
| 5.2 | [LangGraph + zero-latency fast-paths](#52-langgraph-for-chat-routing--zero-latency-fast-paths) | Agents | ✅ Implemented |
| 5.3 | [Local TEI neural sidecars](#53-local-neural-embedding--reranking-via-tei-sidecars) | Agents | ✅ Implemented |
| 5.4 | [Real-time HITL via SSE](#54-real-time-hitl-escalation--sse-event-streaming) | Agents | ✅ Implemented |
| 5.5 | [Tool-side multitenancy](#55-tool-side-multitenancy--query-rewriting) | Agents | ✅ Implemented |
| 5.6 | [HITL correction distillation loop](#56-hitl-correction-distillation-loop) | Agents | 🗺 Roadmap |
| 5.7 | [Domain-agnostic engine design](#57-domain-agnostic-engine-design) | Agents | ✅ Implemented |
| 5.8 | [App Router UI & synchronized provenance viewer](#58-app-router-ui--synchronized-provenance-viewer) | UI | ✅ Implemented |
| 6.1 | [Partition-keyed consumer group scaling](#61-partition-keyed-consumer-group-scaling) | Scale | ✅ Implemented |
| 6.2 | [Centralized model inference sidecars](#62-centralized-model-inference-sidecars) | Scale | ✅ Implemented |
| 6.3 | [Stateless task claiming via SKIP LOCKED](#63-stateless-task-claiming-via-for-update-skip-locked) | Scale | ✅ Implemented |
| 6.4 | [Atomic upsert keys for safe re-balancing](#64-atomic-upsert-keys-for-safe-re-balancing) | Scale | ✅ Implemented |
| 6.5 | [Dual Compose decoupled infra backplane](#65-dual-compose-decoupled-infra-backplane) | Scale | ✅ Implemented |

---

## Part 1 — Ingestion & Routing (Go)

<details>
<summary><strong>1.1 Zero-copy streaming ingress</strong></summary>

**Service:** `api-gateway`

**Decision:** Stream multipart uploads to S3 with `mime/multipart.Reader`; publish protobuf `IngestEvent` after object lands.

**Rejected:** `ReadAll` into RAM — OOM on large PDFs.

**Why:** `api-gateway` never buffers the upload body in memory. Each incoming byte is piped directly to the S3 multipart upload stream, enabling stateless horizontal scaling behind an L7 load balancer.

**See:** `apps/api-gateway/decision.md`

</details>

<details>
<summary><strong>1.2 Dedup chain before GPU</strong></summary>

**Service:** `triage-worker`

**Decision:** Chain-of-responsibility: exact SHA-256 Redis key → version-update metadata path → DLQ after Redis fail-count.

**Note:** Full MinHash LSH is aspirational — today's second stage honors `is_version_update` metadata.

**See:** `apps/triage-worker/decision.md`

</details>

<details>
<summary><strong>1.3 SQS buffer → Kafka</strong></summary>

**Services:** `sqs-kafka-bridge`, `s3-connector`

**Decision:** AWS S3 notifications → SQS/ElasticMQ → Kafka discovery topic → connector dedup → gateway upload.

**See:** `apps/sqs-kafka-bridge/decision.md`, `apps/s3-connector/decision.md`

</details>

<details>
<summary><strong>1.4 Dual Ingestion & Structured Fast-Path Routing</strong></summary>

**Service:** `schema-aligner`

**Decision:** Inspect incoming document types via `doc_router`. Structured digital filings (SEC iXBRL HTML or Indian MCA/BSE XBRL XML) bypass VLM rendering entirely and parse embedded taxonomy tags directly with near 100% precision. Unstructured PDFs/images route to `gpu-extractor`.

**See:** `apps/schema-aligner/decision.md`

</details>

<details>
<summary><strong>1.5 Protobuf v3 & Buf Codegen Stubs</strong></summary>

**Package:** `packages/contracts`

**Decision:** Define all inter-service Kafka payloads (`IngestEvent`, `CitationPayload`) and visual layout trees (`DocumentDOM`, `Node`) strictly in `proto/prism/v1/*.proto` as Protocol Buffer v3 schemas. Checked-in stubs in `gen/{go,python,ts}` are compiled using Buf (`npx buf generate`) for offline, zero-dependency container builds.

**See:** `packages/contracts/README.md`

</details>

---

## Part 2 — Vision & Layout (GPU)

<details>
<summary><strong>2.1 Element-level routing</strong></summary>

**Service:** `gpu-extractor`

**Decision:** Layout boxes (RT-DETR / Docling classes) route per element — text → cheap PyMuPDF path, table/KV → VLM path. Not whole-document monolithic VLM.

**Why:** Avoids spending GPU on text that PyMuPDF can read perfectly. GPU budget reserved for visual tables and forms.

**See:** `apps/gpu-extractor/decision.md`

</details>

<details>
<summary><strong>2.2 Reading order — 1D cluster + X sort</strong></summary>

**Service:** `gpu-extractor`

**Decision:** Geometric Y-clustering (ε ≈ 15px) + X-sort for multi-column pages instead of naive PDF scrape order.

**Why:** PDF text stream order is publication order, not reading order on multi-column pages. Clustering by Y-position into "line rows" then sorting left-to-right within each row reconstructs natural reading order without loading a full LayoutLM model.

**See:** `apps/gpu-extractor/decision.md`

</details>

---

## Part 3 — Alignment & Verification

<details>
<summary><strong>3.1 Structured outputs, not in-process outlines</strong></summary>

**Service:** `schema-aligner`

**Decision:** Dynamic Pydantic models from `registry.json` + Instructor / OpenAI-compatible structured decode (vLLM optional).

**Rejected:** Free-form JSON + retry soup; tying workers to local `outlines` logit masking.

**Why:** Instructor gives schema-faithful decode without requiring specific kernel patching. The registry-driven approach means new table types can be added without code changes.

**See:** `apps/schema-aligner/decision.md`

</details>

<details>
<summary><strong>3.2 Critics + Reflexion before HITL</strong></summary>

**Service:** `schema-aligner`

**Decision:** Declarative critic packs emit structured `CriticResult`. Bounded Reflexion repair loop feeds equation errors back into prompt. Then DLQ/HITL.

| Critic | Formula |
|---|---|
| Balance Sheet | Assets = Liabilities + Equity |
| Income Statement | PAT = PBT − Tax |
| Cash Flow | Rollup reconciliation |
| Bank Statement | Running balance check |

**See:** `apps/schema-aligner/decision.md`

</details>

<details>
<summary><strong>3.3 Context fields injected, not copied</strong></summary>

**Service:** `schema-aligner`

**Decision:** Inject `context_*` fields (entity, period, currency, scale) at compile time from bifurcation context.

**Rejected:** Duplicating those keys in every registry table schema.

**See:** `apps/schema-aligner/decision.md`

</details>

<details>
<summary><strong>3.4 Row-Oriented Chunking over Columnar Parallel Arrays</strong></summary>

**Service:** `schema-aligner`

**Decision:** Extract large financial tables in small row chunks (default 10 rows) as typed Pydantic objects, then merge in Python.

**Rejected:** Columnar parallel arrays (column-length index drift) or single-prompt whole-table generation.

**Why:** LLMs frequently produce arrays of mismatched lengths when asked to generate columnar data. Row-oriented chunks eliminate this class of corruption entirely.

**See:** `apps/schema-aligner/decision.md`

</details>

---

## Part 4 — Storage & CDC

<details>
<summary><strong>4.1 Hybrid JSONB rows + upserts</strong></summary>

**Service:** `storage-sync`

**Decision:** `extracted_tables` table with `strict_columns` JSONB; `ON CONFLICT (document_id, node_id, row_index) DO UPDATE`.

**Why:** JSONB gives schema flexibility for varying table shapes while the composite key guarantees exactly-once semantics across Kafka retries.

**See:** `apps/storage-sync/decision.md`

</details>

<details>
<summary><strong>4.2 Eventual consistency over multi-write</strong></summary>

**Service:** `storage-sync`

**Decision:** Kafka-driven sync + optional Debezium observer. Postgres lands first; vectors and graph triples catch up asynchronously.

**Rejected:** Distributed transactions across Postgres / Neo4j / Qdrant from the aligner hot path.

**See:** `apps/storage-sync/decision.md`, `infra/decision.md`

</details>

<details>
<summary><strong>4.3 Registry → SQL views → Cube</strong></summary>

**Services:** `storage-sync`, `infra/cube`

**Decision:** Generate `view_*` SQL views from `registry.json`. Cube YAML generated from the same registry with tenant filter rewrite applied by the AST tool wrapper.

**See:** `apps/storage-sync/decision.md`, `infra/decision.md`

</details>

<details>
<summary><strong>4.4 Graph triple ingestion via pre-filtering & UNWIND batching</strong></summary>

**Services:** `storage-sync`, `agentic-brain`

**Decision:** Pre-filter text nodes for strategic financial keywords before dispatching to Kafka graph topic. Ingest triples via single-transaction Neo4j `UNWIND` batches.

**Why:** Eliminates unnecessary graph lock contention. Only nodes containing entity signals (related party, subsidiary, auditor, etc.) hit Neo4j at all.

**See:** `apps/storage-sync/decision.md`, `apps/agentic-brain/decision.md`

</details>

---

## Part 5 — Agentic Layer & UI

<details>
<summary><strong>5.1 Deterministic task registry</strong></summary>

**Service:** `agentic-brain`

**Decision:** `/task` uses an explicit agent registry (not LLM-authored code execution or Celery).

**Why:** Predictable, auditable task execution. The LLM picks which task to run by name; it does not write or execute arbitrary code.

**See:** `apps/agentic-brain/decision.md`

</details>

<details>
<summary><strong>5.2 LangGraph for chat routing & zero-latency fast-paths</strong></summary>

**Service:** `agentic-brain`

**Decision:** Parallel fan-out to SQL / Cypher / Vector under a typed graph state. Sub-<1ms sub-agent fast-paths for non-analytical queries skip costly database fan-out entirely.

**See:** `apps/agentic-brain/decision.md`

</details>

<details>
<summary><strong>5.3 Local neural embedding & reranking via TEI sidecars</strong></summary>

**Service:** `agentic-brain`

**Decision:** Decouple dense vector embedding (`bge-small-en-v1.5`) and cross-encoder reranking (`bge-reranker-base`) into HuggingFace TEI microservices (`:8085` and `:8086`).

**Why:** Prevents Python GIL bottlenecks during hybrid RAG. Workers call the TEI HTTP endpoint concurrently with no GIL contention. Also avoids duplicating model weights across worker replicas.

**See:** `apps/agentic-brain/decision.md`

</details>

<details>
<summary><strong>5.4 Real-time HITL escalation & SSE event streaming</strong></summary>

**Services:** `schema-aligner`, `web-dashboard`

**Decision:** Critic failure DLQ events are pushed via Server-Sent Events (SSE) directly to the web dashboard — real-time HITL queue without polling.

**See:** `apps/web-dashboard/decision.md`, `apps/schema-aligner/decision.md`

</details>

<details>
<summary><strong>5.5 Tool-side multitenancy & query rewriting</strong></summary>

**Service:** `agentic-brain`

**Decision:** Multi-tenancy isolation (`tenant_id`) enforced at the database driver/tool wrapper layer via AST rewriting — never relying on prompt instructions.

**Rejected:** Asking the LLM to remember `WHERE tenant_id = …` in prompt strings.

**Why:** Prompt-based isolation is trivially bypassable via prompt injection. AST rewriting is deterministic and cannot be influenced by user input.

**See:** `apps/agentic-brain/decision.md`

</details>

<details>
<summary><strong>5.6 HITL correction distillation loop</strong></summary>

**Services:** `web-dashboard`, `schema-aligner`

**Decision:** Human corrections approved in HITL are saved as structured JSON patch deltas and exported (`scripts/export_corrections.py`) to build fine-tuning goldens for smaller extraction models.

**Status:** 🗺 Roadmap — patch delta export implemented; LoRA fine-tuning pipeline planned.

**See:** `apps/web-dashboard/decision.md`, `apps/schema-aligner/decision.md`

</details>

<details>
<summary><strong>5.7 Domain-agnostic engine design</strong></summary>

**Services:** `schema-aligner`, `storage-sync`, `agentic-brain`

**Decision:** Financial filings serve as the primary high-complexity target domain. The pipeline, schema registry, and tri-modal RAG are 100% domain-agnostic and extendable to Healthcare, Legal, and Insurance by swapping registry schemas and graph prompts.

</details>

<details>
<summary><strong>5.8 App Router UI & Synchronized Provenance Viewer</strong></summary>

**Service:** `web-dashboard`

**Decision:** Next.js 14 App Router dashboard with TailwindCSS, Zustand client stores, real-time SSE proxy (`app/api/brain/.../route.ts`), and interactive PDF page coordinate canvas mapping extracted financial tables directly back to source bounding box coordinates.

**Why:** Allows analysts to verify extraction accuracy directly against the original PDF visual coordinates without toggling separate viewers. Real-time SSE streaming ensures HITL review queues and chat responses render progressively without polling overhead.

**See:** `apps/web-dashboard/README.md`

</details>

---

## Part 6 — Horizontal Scalability

<details>
<summary><strong>6.1 Partition-keyed consumer group scaling</strong></summary>

**Services:** `triage-worker`, `gpu-extractor`, `schema-aligner`, `storage-sync`

**Decision:** All compute-intensive processing runs as stateless Kafka consumer groups keyed by `document_id` / `tenant_id`.

```bash
docker-compose up --scale gpu-extractor=4 --scale schema-aligner=8
```

**Rejected:** In-process threading queues or synchronous HTTP chain calls between workers.

**See:** `apps/gpu-extractor/decision.md`, `apps/schema-aligner/decision.md`

</details>

<details>
<summary><strong>6.2 Centralized model inference sidecars</strong></summary>

**Services:** `gpu-extractor`, `schema-aligner`, `agentic-brain`

**Decision:** Decouple heavy neural models (vLLM, PaddleOCR-VL, HuggingFace TEI) into dedicated HTTP/gRPC inference servers (`:8004`, `:8085`, `:8086`). Worker replicas make lightweight async HTTP calls.

**Rejected:** Loading 7B model weights directly inside each worker process (multiplies VRAM by replica count).

**Why:** Worker replicas scale on cheap CPU instances. GPU resources scale independently behind centralized endpoints guarded by worker-side `asyncio.Semaphore`.

**See:** `apps/gpu-extractor/decision.md`, `apps/agentic-brain/decision.md`

</details>

<details>
<summary><strong>6.3 Stateless task claiming via FOR UPDATE SKIP LOCKED</strong></summary>

**Service:** `agentic-brain`

**Decision:** Background task workers claim pending jobs from Postgres via `SELECT ... FOR UPDATE SKIP LOCKED`.

**Rejected:** Distributed Redis lock management or Celery/RQ infrastructure overhead.

**Why:** N worker replicas poll the task queue concurrently without lock contention, double-claiming, or deadlocks.

**See:** `apps/agentic-brain/decision.md`

</details>

<details>
<summary><strong>6.4 Atomic upsert keys for safe re-balancing</strong></summary>

**Service:** `storage-sync`

**Decision:** Postgres writes enforce composite natural keys `(document_id, node_id, row_index)`. Qdrant vectors use deterministic UUIDv5 from `(document_id, node_id)`.

**Why:** Guaranteed idempotency across Kafka partition re-balances, network retries, or worker crashes. Re-processing the same event never creates duplicate rows or vector drift.

**See:** `apps/storage-sync/decision.md`

</details>

<details>
<summary><strong>6.5 Dual Compose Decoupled Infra Backplane</strong></summary>

**Subsystem:** `infra`

**Decision:** Decouple shared infrastructure data stores, CDC pipeline, and LGTM telemetry into `infra/docker-compose.yml` (`Postgres`, `Kafka`, `Debezium`, `Qdrant`, `Neo4j`, `Redis`, `ElasticMQ`, `S3Mock`, `Cube`, `Loki`, `Tempo`, `Grafana`) separate from product app containers in root `docker-compose.yml`.

**Why:** Allows core stores and observability to run persistently while product microservice containers can be rebuilt, scaled, or debugged independently without resetting database states or restarting the entire stack.

**See:** `infra/README.md`

</details>

---

## 🗺 Future Horizons

| # | Item | Notes |
|---|---|---|
| 1 | **HITL → LoRA distillation** | Patch deltas as LoRA training data for smaller constrained models |
| 2 | **Neo4j native vectors** | Optional Qdrant consolidation for native GraphRAG |
| 3 | **KEDA on Kafka lag** | Auto-scale worker replicas dynamically from consumer lag metrics |
| 4 | **S3 byte-range fan-out** | Faster ingest for multi-GB objects via parallel Go range requests |
