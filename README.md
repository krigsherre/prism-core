# Prism Core

Prism Core turns messy, unstructured business documents (SEC 10-K filings, Indian Annual Reports, vendor invoices, bank exports) into structured, mathematically validated data you can query — featuring layout-aware extraction, declarative accounting critics, real-time HITL escalation, and tri-modal agentic RAG over Postgres, Neo4j, and Qdrant.

**Architecture:** [`architecture.md`](architecture.md) · **Umbrella ADRs:** [`decisions.md`](decisions.md) · **Research Papers:** [`research.md`](research.md)

---

## Documentation Map

| Document | Purpose |
|----------|---------|
| [`README.md`](README.md) | Primary project showcase, quickstart, testing guide, and feature matrix |
| [`architecture.md`](architecture.md) | System architecture, sequence diagrams, microservices map, and pipeline mechanics |
| [`decisions.md`](decisions.md) | Cross-cutting Architecture Decision Records (ADRs) |
| [`research.md`](research.md) | Academic papers and industry implementations mapped to design choices |
| `apps/*/README.md` + `decision.md` | Microservice-specific runbooks and local ADRs |
| [`infra/README.md`](infra/README.md) | Sidecars (ElasticMQ, S3Mock, Cube, CDC, OTel observability stack) |
| [`packages/contracts/README.md`](packages/contracts/README.md) | Shared Protobuf contracts & Buf codegen |

---

## The Vision: Structured Data You Can Defend

Most document AI demos upload a PDF, call a monolithic vision model, stash raw JSON, and provide a generic chat box. That approach fails on real business filings: columns quietly shift, numbers break accounting rules, and models guess when they should escalate.

Prism Core defines success as **structured data you can defend — and an explicit path when you can’t**:

- **In scope:** Zero-copy upload streaming, dual-path ingestion (iXBRL fast-path vs. visual layout VLM), schema alignment with declarative accounting critics ($\text{Assets} = \text{L} + \text{E}$, $\text{PAT} = \text{PBT} - \text{Tax}$), multi-store sync (Postgres, Neo4j, Qdrant), real-time HITL operator escalation, and tri-modal agentic RAG.
- **Out of scope (on purpose):** Generic chat with every document on Earth. Prism Core focuses deeply on complex financial statements, annual reports, invoices, and receipts.

---

## High-Level Pipeline

```text
Upload Stream → Kafka → triage (dedupe) → Router (iXBRL fast-path vs. GPU layout extract)
                     → split tables vs text → align to schema → accounting critics gate
                     → Postgres (and eventual sync to Neo4j graph + Qdrant vectors)
                     → Agentic Brain (tri-modal SQL | Cypher | Vector RAG)
```

When accounting critics fail, a bounded **Reflexion loop** feeds the exact validation error back to the model context for auto-repair. If retries expire or fail terminally, the record is pushed in real time via SSE to the **HITL Reviewer** in the Web Dashboard.

---

## Deep Technical Highlights

1. **Dual Ingestion Engine & Fast-Path Parsing**:
   - Fast-path SEC EDGAR iXBRL HTML tag parser (`ixbrl_parser.py`) and Indian MCA / BSE XBRL XML parser (`mca_xbrl_parser.py`) bypass VLM extraction for structured digital filings with near 100% precision.
2. **Reading Order & Layout Clustering**:
   - Multi-column pages are clustered along the 1D Y-axis ($\varepsilon \approx 15\text{px}$) and sorted by X-coordinates before passing to LLMs/VLMs, preventing text mashing across columns.
3. **Element-Level Routing**:
   - Text boxes use PyMuPDF; only hard visual regions/tables hit VLMs. GPU extraction work is batched dynamically.
4. **Row Chunks over Giant Columnar Arrays**:
   - Extracts tables in small row chunks rather than monolithic arrays, eliminating column index-shift corruption.
5. **SEC 10-K & Ind AS Multi-Jurisdiction Engine**:
   - Native dual support for **SEC 10-K (US-GAAP)** and **Indian Annual Reports (Ind AS / Schedule III)** with automated jurisdiction detection.
6. **Scale Exclusion Protection & Indian Numerics**:
   - Field-level scale exclusion for per-share metrics (Basic/Diluted EPS) and share counts; native support for Crores ($10^7$), Lakhs ($10^5$), and Indian 2-digit comma grouping (`1,00,00,000`).
7. **Cross-Page Table Stitching & Multi-Period Unpivoting**:
   - Automatic continuation of split tables across page boundaries (`table_stitcher.py`) and comparative multi-period unpivoting (`2024`, `2023`, `2022`).
8. **Declarative Accounting Critics & Fail-Closed Safety**:
   - Hard mathematical verification ($\text{Assets} = \text{L} + \text{E}$, Cash Flow rollups, Bank running balance). Syntactically valid JSON that violates accounting rules fails closed and escalates to HITL.
9. **HITL Safety Net as a Product Feature**:
   - Non-standard schedules never block the ingest queue. Operators can click **"Approve as Generic Table"** or **"Divert to RAG"** directly in the Web Dashboard.
10. **CDC & Kafka Decoupling**:
    - Idempotent upserts `(document_id, node_id, row_index)` to Postgres first; vector embeddings and graph triples catch up asynchronously via Kafka/CDC.
11. **Autonomous AI Employee Agents**:
    - Specialized AI Employee roles (*Forensic Accounting Auditor*, *Regulatory Compliance Officer*, *Credit Risk Analyst*, *Research Assistant*) with self-verification audit critic nodes.
12. **Domain-Agnostic Core Engine**:
    - Extensible schema registry and tri-modal RAG engine adaptable to Healthcare, Legal, and Insurance domains by updating registry schemas and graph prompts.

---

## Financial Domain Adaptation & Fine-Tuning Strategy

Instead of relying solely on generic LLM fine-tuning (which risks memorizing numbers and hallucinating on unseen filings), Prism Core employs a **hybrid domain adaptation strategy**:

1. **Fine-Tuned Layout & Vision Engine**: Uses PaddleOCR-VL and SmolDocling-256M fine-tuned specifically for financial table bounding boxes, multi-column reading order, and page header propagation.
2. **Taxonomy & Schema Fine-Tuning**: Schema registry aligned with SEC US-GAAP and Indian Ind AS / Schedule III standards, supported by 110+ domain aliases (*PAT, PBT, Finance Costs, Other Equity, CWIP*).
3. **Guided Decoding > Pure LLM Fine-Tuning**: Enforces strict Pydantic JSON schema constraints during LLM decoding, guaranteeing 100% mathematical structural precision on unseen filings.

---

## Prerequisites

- Docker + Docker Compose v2
- Go **1.25+** (ingress / triage workers)
- Python **3.10–3.12** + Poetry (ML / schema-aligner / storage-sync / agentic-brain)
- Node **20+** (for `web-dashboard` local development)
- GPU optional (recommended for `gpu-extractor` / local vLLM sidecars)

---

## Quick Start

```bash
# 1. Clone & setup environment
cp .env.example .env

# 2. Start the full product stack
make up
```

Access the application surfaces:
- **Web Dashboard**: http://localhost:3000
- **API Gateway**: http://localhost:8080
- **Agentic Brain API**: http://localhost:8001

---

## Service Port Matrix

| Surface / Service | Port | Description |
|-------------------|------|-------------|
| Web Dashboard | `3000` | Operator UI (queue, real-time HITL cards, multi-modal chat, agent list) |
| API Gateway | `8080` | High-throughput Go ingress API (zero-copy upload streaming) |
| Agentic Brain | `8001` | LangGraph chat API + deterministic `/task` agent runner |
| TEI Embeddings Server | `8085` | Local HuggingFace Text Embeddings Inference (`bge-small-en-v1.5`) |
| TEI Reranker Server | `8086` | Local HuggingFace Cross-Encoder Reranker (`bge-reranker-base`) |
| Cube BI Engine | `4000` / `4001` | Semantic data model & REST/SQL API for analytical queries |
| Postgres Database | `5432` | Primary relational store (`extracted_tables` JSONB + registry views) |
| Kafka / Zookeeper | `9092` / `2181` | Async event backbone between microservices |
| Redis | `6379` | Hash deduplication cache & triage retry state |
| Neo4j Graph DB | `7474` (HTTP) / `7687` (Bolt) | Entity-relationship graph database |
| Qdrant Vector DB | `6333` (HTTP) / `6334` (gRPC) | Dense vector search engine for prose chunks |

---

## Development & Testing

Run unit and integration test suites across all microservices:

```bash
# Go Microservices
cd apps/api-gateway && go test ./...
cd apps/triage-worker && go test ./...
cd apps/s3-connector && go test ./...
cd apps/sqs-kafka-bridge && go test ./...

# Python Microservices
cd apps/schema-aligner && poetry run pytest
cd apps/storage-sync && poetry run pytest
cd apps/agentic-brain && poetry run pytest
cd apps/gpu-extractor && poetry run pytest

# Next.js Dashboard
cd apps/web-dashboard && npm test -- --watchAll=false
```

*Goldens directory*: `apps/schema-aligner/evals/golden/`.

---

## Repository Layout

```text
apps/
  api-gateway/        Go zero-copy upload streaming edge server
  sqs-kafka-bridge/   Go AWS SQS/ElasticMQ to Kafka bridge worker
  s3-connector/       Go S3 bucket notification consumer & deduplicator
  triage-worker/      Go Redis exact-hash deduplication worker
  gpu-extractor/      Python layout detection (RT-DETR) & VLM extraction worker
  schema-aligner/     Python Instructor alignment, iXBRL fast-paths, accounting critics
  storage-sync/       Python bifurcation engine, Postgres upserts, Neo4j UNWIND, Qdrant
  agentic-brain/      Python LangGraph tri-modal RAG chat & autonomous agent runner
  web-dashboard/      Next.js 14 operator interface (chat, queue, HITL, agents)
packages/contracts/   Protobuf schemas & Buf codegen (`IngestEvent`, `DocumentDOM`)
infra/                Sidecar compose, Cube schemas, OTel / Grafana stack
docker-compose.yml    Canonical product stack compose configuration
Makefile              Task runner (`make up`, `make down`, `make test`)
.env.example          Canonical environment variable template
```

---

## Ops & Horizontal Scalability

- **Stateless Edge Streaming**: `api-gateway` streams uploads directly to object storage without memory buffering, enabling stateless horizontally scaled L7 load balancing.
- **Kafka Partition-Keyed Worker Scaling**: Heavy extraction and alignment workers run as stateless consumer groups. Scale ingest capacity by adding Kafka topic partitions and worker container replicas (`docker-compose up --scale gpu-extractor=4 --scale schema-aligner=8`).
- **Decoupled Centralized Model Sidecars**: vLLM and HuggingFace TEI microservices (`:8004`, `:8085`, `:8086`) run as shared sidecars. Worker containers scale on inexpensive CPU nodes without duplicating model VRAM weights.
- **Stateless Task Claiming (`SKIP LOCKED`)**: Background agents in `agentic-brain` claim jobs directly from Postgres using `FOR UPDATE SKIP LOCKED`, allowing concurrent worker execution without Redis locks.
- **OpenTelemetry Context Propagation**: OTel headers injected into Kafka message headers propagate trace context end-to-end across Go and Python microservices into Grafana (Loki/Tempo).
- **Database Migrations**: Automated relational schema migrations managed via Alembic (`apps/storage-sync/alembic`).
