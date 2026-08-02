# Architecture Decision Record (ADR): Storage Sync

Foundational decisions for the `storage-sync` worker — DOM bifurcation, idempotent Postgres sync, Qdrant dual-routing, and event-sourced CDC.

---

## 1. Hybrid Relational + JSONB Storage

**Decision:** Persist aligned rows in a single `extracted_tables` relation with a relational skeleton and dynamic payloads in `strict_columns` / `unmapped_jsonb` JSONB.

**Alternatives Evaluated:**
* One physical table per registered schema (DDL per tenant change).
* Pure document store (Mongo-style) for all extractions.

**Why Chosen:** Tenant schemas evolve faster than migration windows allow. JSONB avoids `ALTER TABLE` churn while Postgres still gives ACID upserts, indexes, and BI-friendly views. Trade-off: analysts do not query raw JSONB — views flatten it.

---

## 2. Row-Level `ON CONFLICT DO UPDATE`

**Decision:** Upsert on composite uniqueness `(document_id, node_id, row_index)`.

**Alternatives Evaluated:**
* Append-only event log + “latest row” views.
* Delete-all-then-insert per document on reprocess.

**Why Chosen:** Kafka is at-least-once; re-runs and cell edits must not duplicate rows or wipe HITL edits. Deterministic `node_id` (extractor DOM) + `row_index` (aligner) make conflict targets stable.

---

## 3. Registry-Driven Postgres Views

**Decision:** On startup, read `schema-aligner` `registry.json` and `CREATE OR REPLACE VIEW` per target table, casting/cleaning JSONB fields (currency, accounting negatives, null tokens).

**Alternatives Evaluated:**
* Force Cube/Tableau authors to write `strict_columns->>'…'` everywhere.
* External dbt/ETL flatten jobs.

**Why Chosen:** BI expects typed flat columns. Putting regex/cast logic in the view keeps the warehouse contract in sync with the registry without a second pipeline.

---

## 4. Bifurcation with Sliding Sibling Context

**Decision:** Walk the DocumentDOM; for tables/KV, build a short look-behind/look-ahead sibling window (headers above, footnotes below) as `parent_section_text`, then dual-route: Kafka `raw_table_doms` for alignment **and** Qdrant embeddings for RAG.

**Alternatives Evaluated:**
* Only the nearest `SECTION_HEADER`.
* Full-page markdown into every LLM/embedding call.

**Why Chosen:** Entity/currency/scale live in nearby nodes, not always in the parent header. Full-page context wastes tokens and contaminates tables. Dual routing serves both Text-to-SQL/BI and fuzzy conversational retrieval.

---

## 5. In-Process Multi-Consumer + Light CDC Observer

**Decision:** One asyncio process gathers status/DLQ/HITL/bifurcation/aligned/auto-promote consumers plus a Kafka observer on `postgres.public.extracted_tables.events` that re-embeds/deletes Qdrant points.

**Why Chosen:** Keeps ops to a single deployable for the sync plane. Postgres remains source of truth; the observer closes the vector gap after SQL writes or deletes without dual-writing from every producer. Cap CDC concurrency via `CDC_MAX_CONCURRENT_INFERENCES`.
