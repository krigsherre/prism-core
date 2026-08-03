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

1. **Reading order** — multi-column pages get clustered on Y then sorted on X before any LLM sees them.  
2. **Don’t GPU everything** — text boxes use PyMuPDF; only hard regions hit VLMs; GPU work is batched.  
3. **Row chunks, not giant columnar arrays** — avoids index-shift corruption on big tables.  
4. **Accounting critics** — valid JSON can still be financially wrong; I fail closed and escalate.  
5. **CDC instead of multi-write** — one store down doesn’t corrupt the others.  
6. **Chat after sync** — SQL / graph / vectors with tenant filters injected by me, not the model.
7. **Big document chunking** — large PDFs are split into chunks to avoid OOMs and context limits, but section headers are carried forward so a table on page 40 still knows whose statement it is.

The ideas came from a real reading list (RT-DETR/Docling, guided decoding, Reflexion, GraphRAG, Kafka/CDC, MinHash, …) — see [`RESEARCH.md`](RESEARCH.md).

Financial verification is wired and testable: `poetry run pytest tests/test_financial_critics.py` and `poetry run python evals/run_eval.py` under `apps/schema-aligner` (includes a broken balance sheet that must be rejected).

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

On **100k+ documents:** the design supports a large corpus and horizontal ingest. Throughput is GPU/aligner-bound — you add replicas and partitions. Local compose is not a load test; don’t claim I soaked 100k on a laptop.

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
