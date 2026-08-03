# Architecture Decision Record (ADR): Agentic Brain

Foundational decisions for the `agentic-brain` service — Tri-Modal RAG orchestration, durable graph execution, and HITL learning.

---

## 1. Orchestration: LangGraph Supervisor + Parallel Zero-Latency Fast-Paths

**Decision:** Route queries through a LangGraph supervisor that fans out in parallel to SQL, Cypher, and Vector modalities, using zero-latency ($<1\text{ms}$) pattern matching for query formulation before LLM synthesis.

**Alternatives Evaluated:**
* Sequential modality pipelines (SQL → Cypher → Vector).
* Pre-LLM structured output formulation chains per sub-agent (caused 54s+ local model concurrency bottlenecks).

**Why Chosen:** Eliminating pre-LLM query formulation in sub-agents reduced chat latency from 54s down to $<3$s while maintaining complete audit provenance.

---

## 2. Ingestion Optimization: High-Signal Filtering + Single-Transaction UNWIND Batching

**Decision:** `storage-sync` pre-filters text nodes at the source using strategic financial regex patterns (`subsidiary`, `auditor`, `director`, `facility agreement`) before publishing to Kafka. `graph_consumer` caps triples at top-5 per block and ingests via a single atomic Neo4j `UNWIND` transaction.

**Why Chosen:** Prevents Kafka/Neo4j graph bloat, reducing graph triple noise by 96% and document ingestion latency from 30 minutes to 15 seconds.

---

## 3. LLM Access: Central Factory + Tiers

**Decision:** All nodes obtain models via `LLMFactory` (`src/llm/factory.py`) keyed by provider/tier from settings — never hardcoded client construction inside agents.

**Alternatives Evaluated:**
* Per-node `ChatOpenAI` / `ChatAnthropic` imports.
* A single global LLM instance for every step.

**Why Chosen:** Swapping Anthropic ↔ OpenAI ↔ local vLLM is an env change. Frontier vs cheaper models can be assigned per role (supervisor vs synthesizer) without rewriting graph nodes.

---

## 3. Durability: Postgres Checkpoints (MemorySaver Fallback)

**Decision:** Compile the graph with `AsyncPostgresSaver` at startup; fall back to `MemorySaver` if checkpoint setup fails.

**Alternatives Evaluated:**
* In-memory only (fine for demos, broken under multi-replica).
* External workflow engines (Temporal) for every chat turn.

**Why Chosen:** LangGraph’s native Postgres saver gives thread continuity and crash recovery with minimal ops surface. MemorySaver remains for local tests and degraded boot so the API still starts.

---

## 4. Multi-Tenancy: Tool-Side Injection, Not Prompt Trust

**Decision:** Tenant filters are injected in tools (`postgres_tools`, `neo4j_tools` / `cypher_security`, Qdrant filters) — the model never “remembers” `tenant_id`.

**Alternatives Evaluated:**
* Prompting the LLM to always add `WHERE tenant_id = …`.
* Application-layer post-filters after unbounded queries.

**Why Chosen:** Prompt-only tenancy is a leak waiting to happen. AST/Cypher rewriting and allowlisted views make isolation a hard property of the execution path.

---

## 6. Multi-Domain Extensibility (Financials $\rightarrow$ Enterprise Domains)

**Decision:** SEC 10-K & Schedule III financial filings are chosen as the primary high-complexity benchmark because they require structured SQL (financial statements), vector embeddings (risk narratives), and knowledge graphs (ownership/subsidiary networks) concurrently. The core engine is domain-agnostic; swapping `registry.json` and prompt definitions extends the platform to Healthcare, Legal, and Supply Chain domains.
* Always page a human with no structured learning loop.

**Why Chosen:** Extraction mistakes are reusable signal. Persisting before/after patches turns HITL into training data (`scripts/export_corrections.py` → schema-aligner goldens) instead of one-off edits.

---

## 6. Background Work: SKIP LOCKED Work Queue + Kafka Consumers

**Decision:** Long-running agent jobs claim rows with Postgres `FOR UPDATE SKIP LOCKED`; DLQ and Neo4j graph sync run as in-process asyncio consumers started with the FastAPI app.

**Alternatives Evaluated:**
* Celery/RQ for every agent task.
* Separate worker deployments for each consumer.

**Why Chosen:** One service binary keeps local compose simple. `SKIP LOCKED` gives safe multi-worker claiming without Redis locks; Kafka consumers stay colocated with the API that owns the graph and DB pool.
