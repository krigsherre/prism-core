<p align="center">
  <img src="apps/web-dashboard/app/icon.png" alt="Prism Core" width="72" />
</p>

<h1 align="center">Prism Core — System Architecture</h1>

<p align="center">
  How Prism Core turns messy business documents into structured data you can query — and what happens when the model is wrong.
</p>

<p align="center">
  <a href="README.md">🏠 README</a> ·
  <a href="decisions.md">🗂 ADRs</a> ·
  <a href="research.md">📚 Research</a> ·
  <a href="infra/README.md">🔧 Infra</a>
</p>

---

## 🎯 The Problem

Most "document AI" demos do this:

```mermaid
flowchart LR
    A[PDF] --> B[Big VLM] --> C[JSON] --> D[Database]
```

That falls apart on real financial PDFs: columns get read in the wrong order, tables shift indexes, numbers look fine as JSON but break basic accounting, and if you write Postgres + Neo4j + Qdrant in one shot you get split-brain when one store dies.

> **Prism Core's scope:** Extract trustworthy rows from messy business docs, refuse to promote junk, and let an analyst ask questions against what actually landed. Depth over coverage.

---

## 💡 The Bet

Accuracy isn't one clever prompt. It's a multi-stage verification pipeline. Each stage kills a specific failure mode, then queries the structured result — not the raw pixels.

```mermaid
flowchart LR
    P1[Document] --> P2{Router:\niXBRL vs Visual?}
    P2 -->|iXBRL / XML| P2A[Deterministic\nFast-Path]
    P2 -->|PDF / Image| P3[Layout +\nReading Order]
    P3 --> P3A[Cheap vs GPU\nExtract]
    P2A --> P4[Schema-Aligned\nRows]
    P3A --> P4
    P4 --> P5[Accounting\nCritics Gate]
    P5 --> P6{OK?}
    P6 -->|yes| P7[Write + CDC Sync]
    P6 -->|no| P8[Reflexion Retry → HITL]
    P7 --> P9[SQL / Graph / Vector RAG]
```

---

## 🗺 High-Level Topology

```mermaid
flowchart TB
    Analyst((Analyst /\nOperator))

    subgraph Platform["Prism Core Platform"]
        UI[Web Dashboard :3000]
        Pipe[Kafka Pipeline]
        Brain[Agentic Brain :8001]
        UI --- Pipe
        UI --- Brain
    end

    S3[(S3 / MinIO)]
    GPU_ML[Layout + vLLM]
    TEI[HuggingFace TEI\nEmbeddings :8085 & Reranker :8086]
    Obs[Grafana / Loki / Tempo]

    Analyst --> UI
    Pipe --> S3
    Pipe --> GPU_ML
    Brain --> TEI
    Pipe -.-> Obs
    Brain -.-> Obs
```

Work moves through Kafka. The UI watches the queue, handles real-time HITL reviews via SSE, and provides multi-modal chat & autonomous agent workflows.

---

## 🔲 Microservices Map

```mermaid
flowchart TB
    subgraph UI_layer["UI"]
        Web["web-dashboard :3000"]
    end

    subgraph Go["Go Services"]
        GW[api-gateway :8080]
        S3C[s3-connector]
        Bridge[sqs-kafka-bridge]
        Triage[triage-worker]
    end

    subgraph Py["Python Workers"]
        Ext[gpu-extractor]
        Align[schema-aligner]
        Sync[storage-sync]
        Brain[agentic-brain :8001]
    end

    subgraph Sidecars["Neural Sidecars"]
        TEI_Emb[TEI Embeddings :8085]
        TEI_Re[TEI Reranker :8086]
    end

    K[(Kafka)]
    R[(Redis)]
    PG[(Postgres)]
    Neo[(Neo4j)]
    Qd[(Qdrant)]

    Web --> GW
    Web --> Brain
    GW --> S3[(S3 Object Store)]
    GW --> K
    S3C --> K
    Bridge --> K
    K --> Triage --> K
    Triage --> R
    K --> Ext --> K
    K --> Align --> K
    K --> Sync
    Sync --> PG
    Sync --> Neo
    Sync --> Qd
    K --> Brain
    Brain --> TEI_Emb
    Brain --> TEI_Re
    Brain --> PG
    Brain --> Neo
    Brain --> Qd
    Brain --> R
```

### Service Roles

| Service | Language | Role |
|---|---|---|
| `api-gateway` | Go | Zero-copy upload stream to S3 + publish `IngestEvent` |
| `sqs-kafka-bridge` | Go | Bridge AWS SQS / ElasticMQ bucket notifications to Kafka |
| `s3-connector` | Go | S3 discovery events → dedupe → queue gateway upload |
| `triage-worker` | Go | Exact-hash dedupe via Redis + versioning route / DLQ |
| `gpu-extractor` | Python | Layout box detection + Y-clustering + VLM OCR → `DocumentDOM` |
| `schema-aligner` | Python | iXBRL fast-path + Instructor alignment + accounting critics + Reflexion |
| `storage-sync` | Python | Bifurcation engine, Postgres JSONB upserts, Qdrant vectors, Neo4j `UNWIND` |
| `agentic-brain` | Python | LangGraph tri-modal RAG (SQL + Cypher + Vector) + `/task` agent runner |
| `web-dashboard` | TypeScript | Operator UI — queue, real-time HITL cards, chat, agent list |

---

## 🔬 Detailed Pipeline Stages

<details>
<summary><strong>Stage 1 — Dual Ingestion: iXBRL Fast-Path vs Visual VLM</strong></summary>

When a document enters `schema-aligner`, the `doc_router` determines if the file is a structured digital filing (SEC iXBRL HTML or Indian MCA/BSE XBRL XML) or a visual document (PDF/Image).

```mermaid
flowchart TB
    Doc[Document Received] --> Router{doc_router}
    Router -->|iXBRL / MCA-XBRL| FastPath[Deterministic XBRL Parser]
    Router -->|Unstructured PDF / Image| VisualPath[GPU Extractor DOM Chunks]

    FastPath --> ExactTaxonomy[Map SEC / MCA Tags Directly]
    VisualPath --> LayoutBox[RT-DETR Box Routing]

    LayoutBox --> ReadOrder[Y-Clustering + X-Sort]
    ReadOrder --> Extract[PyMuPDF / VLM]
    Extract --> StructAlign[Instructor Pydantic Decode]

    ExactTaxonomy --> Critics[Accounting Critics Gate]
    StructAlign --> Critics
```

- **iXBRL Fast-Path** (`ixbrl_parser.py`, `mca_xbrl_parser.py`) — bypasses VLM rendering, parses XBRL taxonomy tags with near 100% precision.
- **Visual VLM Path** (`gpu-extractor`) — RT-DETR layout box detection, 1D Y-clustering (ε ≈ 15px) for multi-column reading order, PyMuPDF for text and VLMs for tables.

</details>

<details>
<summary><strong>Stage 2 — Accounting Critics & Bounded Reflexion Repair</strong></summary>

Before any extracted row is promoted to Postgres, it must pass declarative accounting critics.

| Rule | Equation |
|---|---|
| Balance Sheet | Assets = Liabilities + Equity |
| Income Statement | PAT = PBT − Tax |
| Cash Flow | Rollup reconciliation |
| Bank Statement | Running balance check |

```mermaid
sequenceDiagram
    participant A as Aligner
    participant C as Critic Pack
    participant K as Kafka
    participant D as DLQ / HITL Consumer
    participant H as Web Dashboard (SSE)

    A->>C: Validate Assets = Liabilities + Equity
    alt Valid Math
        A->>K: Publish mapped_rows
    else Critic Violation (Fixable)
        loop Max 3 Reflexion Retries
            A->>A: Append critic error to prompt context
            A->>A: Re-generate structured JSON
            A->>C: Re-validate
        end
        alt Fixed
            A->>K: Publish mapped_rows
        else Still Failing
            A->>K: Route to DLQ
            K->>D: Process DLQ message
            D->>H: Push real-time HITL card via SSE
        end
    else Terminal Failure
        A->>K: Route immediately to DLQ
        K->>D: Process DLQ
        D->>H: Push HITL card via SSE
    end
```

</details>

<details>
<summary><strong>Stage 3 — Storage Sync & Graph UNWIND Batching</strong></summary>

Aligned rows land in Postgres with idempotent key `(document_id, node_id, row_index)`. Prose nodes become dense vector embeddings via the local TEI sidecar (`:8085`) written to Qdrant.

```mermaid
flowchart TB
    DOM[DocumentDOM] --> Split{Node Type?}
    Split -->|Table Node| Align[schema-aligner]
    Split -->|Text / Prose Node| PreFilter[Keyword Entity Filter]

    Align -->|Passed Critics| PG[(Postgres extracted_tables)]
    Align -->|Failed Critics| HITL[HITL Queue]

    PreFilter -->|Financial Entities Present| GraphBatcher[Neo4j Cypher UNWIND Batcher]
    PreFilter -->|General Text| VectorEmb[TEI Embeddings :8085]

    GraphBatcher --> Neo4j[(Neo4j Graph Database)]
    VectorEmb --> Qdrant[(Qdrant Vector Database)]
```

`storage-sync` pre-filters text nodes for financial domain entities before dispatching graph triples. Entities are ingested in single-transaction `UNWIND` Cypher batches, eliminating graph lock contention.

</details>

<details>
<summary><strong>Stage 4 — Agentic Brain & Zero-Latency Fast-Paths</strong></summary>

The `agentic-brain` orchestrates Q&A via a LangGraph state machine with parallel tri-modal fan-out.

```mermaid
flowchart TB
    Query[User Chat Query] --> FastPath{Fast-Path Router}
    FastPath -->|Greeting / Meta / Trivial| Sub1ms[<1ms Direct Answer]
    FastPath -->|Analytical Question| LangGraph[LangGraph State Engine]

    LangGraph --> ParallelFanOut{Parallel Execution}
    ParallelFanOut --> SQL[Postgres SQL Engine]
    ParallelFanOut --> Cypher[Neo4j Cypher Engine]
    ParallelFanOut --> Vector[Qdrant Hybrid Vector Search]

    Vector --> TEI_Re[TEI Reranker :8086]
    TEI_Re --> Synthesis

    SQL --> Synthesis[Response Synthesizer]
    Cypher --> Synthesis
    Synthesis --> FinalResp[Final Answer + Citations]
```

- **Zero-Latency Fast-Paths** — non-analytical queries skip costly database fan-out entirely, answering in <1ms.
- **Tri-Modal Fan-Out** — SQL, Cypher graph traversal, and hybrid vector search run concurrently with tenant ID isolation enforced at the tool wrapper level.

</details>

---

## 🗄 Data Schema

```mermaid
erDiagram
    DOCUMENT_JOBS ||--o{ EXTRACTED_TABLES : has
    EXTRACTED_TABLES ||--o| HITL_REQUESTS : may_need

    EXTRACTED_TABLES {
        string document_id
        string node_id
        int row_index
        string mapping_status
        jsonb strict_columns
        jsonb unmapped_jsonb
    }
```

- `strict_columns` — validated, clean row data.
- `unmapped_jsonb` — schema drift, critic failure logs, and reflexion attempts surfaced in the HITL card UI.

---

## 📡 Observability

```mermaid
flowchart LR
    Ingress[api-gateway] -->|Inject OTel Header| Kafka[(Kafka Header)]
    Kafka -->|Extract OTel Header| Worker[Python / Go Worker]
    Worker -->|JSON Logs + trace_id| Loki[Loki]
    Worker -->|Spans| Tempo[Tempo]
    Loki --> Grafana[Grafana Dashboard]
    Tempo --> Grafana
```

OTel context propagated through Kafka message headers end-to-end across Go and Python microservices.

---

## 📈 Horizontal Scalability

<details>
<summary><strong>Scaling architecture diagram</strong></summary>

```mermaid
flowchart TB
    Client((Ingest Firehose)) --> LB[L7 Load Balancer]

    subgraph Edge["Edge Layer"]
        GW1[api-gateway Replica 1]
        GW2[api-gateway Replica 2]
        LB --> GW1
        LB --> GW2
    end

    GW1 --> S3[(S3 / MinIO)]
    GW2 --> S3
    GW1 --> Kafka[(Kafka Partitioned Topics)]
    GW2 --> Kafka

    subgraph Workers["Scalable Worker Replicas"]
        Ext1[gpu-extractor Replica 1]
        Ext2[gpu-extractor Replica 2]
        Align1[schema-aligner Replica 1]
        Align2[schema-aligner Replica 2]
    end

    Kafka -->|Partition Key: doc_id| Ext1
    Kafka -->|Partition Key: doc_id| Ext2
    Kafka -->|Partition Key: doc_id| Align1
    Kafka -->|Partition Key: doc_id| Align2

    subgraph Sidecars["Centralized GPU / Neural Sidecars"]
        vLLM[vLLM :8004]
        TEI_Emb[TEI Embeddings :8085]
        TEI_Re[TEI Reranker :8086]
    end

    Ext1 --> vLLM
    Ext2 --> vLLM
    Align1 --> vLLM
    Align2 --> vLLM
```

</details>

| Mechanic | How |
|---|---|
| Stateless Edge Streaming | `api-gateway` streams directly to S3, zero memory buffering |
| Kafka Consumer Group Scaling | `docker-compose up --scale gpu-extractor=4 --scale schema-aligner=8` |
| Decoupled Model Sidecars | Workers scale on CPU nodes; GPU inference scales independently |
| Stateless Task Claiming | `FOR UPDATE SKIP LOCKED` — no Redis locks needed |
| Idempotent Re-Balancing | Composite natural keys `(document_id, node_id, row_index)` + UUIDv5 |

---

## 🔚 End-to-End Summary

```mermaid
flowchart TB
    UI[Web Dashboard :3000]

    UI --> Ingest[Upload Stream]
    Ingest --> K[(Kafka)]
    K --> Ex[Visual Extractor OR iXBRL Fast-Path]
    Ex --> Al[Aligner + Accounting Critics]
    Al -->|Passed| DB[(Postgres + Neo4j + Qdrant)]
    Al -->|Failed| H[Real-Time HITL Queue]
    DB --> Chat[Agentic Brain + TEI Reranker]
    Chat --> UI
    H --> UI
```
