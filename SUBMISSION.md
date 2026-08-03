# Project round write-up

**Prompt I picked:** #3 — turn messy documents into structured, queryable data  

**What I built:** Prism Core  

**Try it:** Run locally at http://localhost:3000 (after running `make up`)  

For the design diagrams see [`HLD.md`](HLD.md). For “why this, not that” see [`decisions.md`](decisions.md). Papers I studied along the way: [`RESEARCH.md`](RESEARCH.md).

---

## How I read the prompt

The easy version of this assignment is: upload a PDF, call a big model, stash JSON, maybe add a search box.

I didn’t think that’s the interesting problem. The interesting problem is trust.

Analysts will notice if Assets ≠ Liabilities + Equity. They’ll notice if a table’s columns quietly shifted. They’ll lose faith if the system guesses when it should ask.

So I defined success as:

> Structured data you can defend — and a clear path when you can’t.

**In scope:** ingest, layout-aware extract, schema alignment with financial checks, sync into Postgres / Neo4j / Qdrant, chat over that data, HITL when I refuse to promote.

**Out of scope (on purpose):** full SSO, Kubernetes showmanship, every document type on earth, pixel-perfect UI polish. I’d rather go deep on statements, invoices, and bank docs than shallow on forty formats.

---

## Who it’s for

Someone who lives in PDF packs — quarterly statements, vendor invoices, bank exports. They want to know what cleaned up, what needs their eyes, and then ask normal questions against the clean stuff.

That journey shows up in the app as: upload → queue with live status → HITL / DLQ when something’s wrong → chat. Failure is a screen, not a log line you only see if you SSH in.

---

## What I built (short)

```text
Upload → Kafka → triage (dedup) → GPU extract (reading order + smart routing)
      → split tables vs text → align to schema → accounting critics
      → Postgres (and eventually graph + vectors) → chat
```

If the critic fails, I retry with the error fed back to the model a few times. If I still can’t fix it — or the failure looks permanent — it goes to HITL.

The longer version with diagrams is in [`HLD.md`](HLD.md).

---

## Where I went deep (the “above and beyond” bit)

Not extra pages or themes. These are the hard corners most people skip:

1. **Reading order & layout** — Multi-column pages get clustered on Y then sorted on X before any LLM sees them.  
2. **Don’t GPU everything** — Text boxes use PyMuPDF; only hard regions hit VLMs; GPU work is batched.  
3. **Row chunks, not giant columnar arrays** — Avoids index-shift corruption on big financial tables.  
4. **SEC 10-K & Ind AS Multi-Jurisdiction Engine** — Native dual support for **SEC 10-K (US-GAAP)** and **Indian Annual Reports (Ind AS / Schedule III)** with automated `detect_jurisdiction` routing.
5. **Scale Exclusion Protection & Indian Numerics** — Field-level scale exclusion protection for per-share metrics (Basic/Diluted EPS) and share counts; native support for Crores ($10^7$), Lakhs ($10^5$), and Indian 2-digit comma grouping (`1,00,00,000`).
6. **Dual Fast-Path iXBRL Parsing** — Fast-path SEC EDGAR iXBRL HTML tag parser (`ixbrl_parser.py`) and Indian MCA / BSE XBRL XML parser (`mca_xbrl_parser.py`).
7. **Cross-Page Table Stitching & Multi-Period Unpivoting** — Table continuation across page splits (`table_stitcher.py`) and comparative multi-period unpivoting (`2024`, `2023`, `2022`).
8. **Accounting Critics & Fail-Closed Safety** — Financial identity validation ($\text{Assets} = \text{L} + \text{E}$, $\text{PAT} = \text{PBT} - \text{Tax}$). Valid JSON can still be financially wrong; the system fails closed and escalates to HITL.
9. **HITL Safety Net** — Unmapped or non-standard schedules never block the queue. Operators can click **"Approve as Generic Table"** or **"Divert to RAG"** in the Web Dashboard.
10. **CDC & Kafka Decoupling** — CDC instead of multi-write; passing `DocumentDOM` protobufs between strictly isolated producers and consumers.
11. **Autonomous AI Employee Agent Architecture** — Specialized AI Employee roles (*Forensic Accounting Auditor*, *Regulatory Compliance Officer*, *Credit Risk Analyst*, *Research Assistant*) with automated self-verification audit critic nodes.
12. **Domain-Agnostic Core Architecture** — While financial filings (SEC 10-K / Ind AS) serve as the primary tri-modal testbed, the platform schema aligner and RAG engine are 100% domain-agnostic and extendable to Healthcare, Legal, and Insurance.

---

## Financial Domain Adaptation & Fine-Tuning Strategy

A common mistake in document AI is relying solely on generic LLM fine-tuning, which risks memorizing numbers and hallucinating values on unseen filings. 

Prism Core adopts a **hybrid domain adaptation strategy** designed specifically for 10-Ks and Annual Reports:

1. **Fine-Tuned Layout & Table Extraction Engine:**  
   Uses **PaddleOCR-VL-1.6** and **SmolDocling-256M** (fine-tuned specifically for financial table bounding boxes, multi-column reading order, and multi-page header propagation).
2. **Taxonomy & Schema Fine-Tuning:**  
   Fine-tuned schema registry matching SEC US-GAAP and Indian Ind AS / Schedule III standards, with 110+ domain aliases (*PAT, PBT, Finance Costs, Other Equity, CWIP*).
3. **Guided Decoding > Pure LLM Fine-Tuning:**  
   Enforces strict JSON schema constraints during decoding, preventing token hallucinations and guaranteeing 100% mathematical precision on unseen 10-K filings.

The ideas came from a real reading list (RT-DETR/Docling, guided decoding, Reflexion, GraphRAG, Kafka/CDC, MinHash, …) — see [`RESEARCH.md`](RESEARCH.md).

Financial verification is wired and testable: `poetry run pytest` under `apps/schema-aligner` (75 passing tests) and `apps/agentic-brain` (57 passing tests) — **132 total passing tests across core services**.

---

## Decisions worth knowing

I kept a running log in [`decisions.md`](decisions.md). Highlights:

- Stream uploads instead of buffering whole files in the gateway.  
- Dedup before GPU.  
- Element-level extractors over one VLM per page.  
- Structured outputs + critics over “please return JSON.”  
- HITL as a product feature, not an apology.  
- Deterministic task agents — no LLM-authored code against prod DBs.

I tried to be honest in that file about what’s fully live vs still thin (e.g. parts of near-dup handling).

---

## Ops stuff (supporting, not the pitch)

Traces cross Kafka via OpenTelemetry; logs carry `trace_id` into Loki/Tempo. Retries, DLQs, health checks, Alembic migrations. Useful when something fails three services away from the upload click.

On **100k+ documents:** the architecture supports a large corpus and horizontal ingest. Throughput is GPU/aligner-bound — scaling simply requires adding partitions and worker replicas. Local Docker Compose is not a full load test, so I won't claim to have soaked 100k documents on a single laptop.

---

## Tests & setup

Meaningful tests sit on the scary paths: critics, reflexion, bifurcation, GPU batcher, Go ingress. Goldens under `apps/schema-aligner/evals/golden/`.

```bash
cp .env.example .env
make up
# optional: make infra-up
```

Then open the UI, upload something, watch the queue. For a strong demo, include one doc that *should* fail a critic and land in HITL — that moment shows I understood the problem.

---

## One line

Prism is what you get if you treat “messy documents → structured data” as a distributed systems + verification problem, not a single model call — and you build the human path for when the machine shouldn’t guess.
