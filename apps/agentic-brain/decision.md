# Architecture Decision Record (ADR): Agentic Brain

Foundational decisions for the `agentic-brain` service — Tri-Modal RAG orchestration, durable graph execution, and HITL learning.

---

## 1. Orchestration: LangGraph Supervisor + Parallel Modalities

**Decision:** Route each query through a LangGraph supervisor that selects one or more of SQL, Cypher, and Vector, fans them out in parallel, then synthesizes.

**Alternatives Evaluated:**
* Single monolithic agent with unbounded tool-calling.
* Sequential modality pipelines (always SQL → Cypher → Vector).

**Why Chosen:** Financial questions often need aggregates *and* relationships *and* prose. Parallel fan-out cuts latency; the supervisor keeps the graph deterministic and inspectable. Retries stay local to each modality (`generate_*` → `execute_*` reflexion) so one bad Cypher does not block SQL.

---

## 2. LLM Access: Central Factory + Tiers

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

## 5. Failure Path: Reflexion → DLQ → HITL → Learning Flywheel

**Decision:** Exhaust in-graph retries, then escalate via DLQ consumer into Redis/Postgres HITL. Resolutions persist corrections, emit dictionary CDC synonyms, and attach few-shots for the next align pass.

**Alternatives Evaluated:**
* Drop failed tasks after N retries.
* Always page a human with no structured learning loop.

**Why Chosen:** Extraction mistakes are reusable signal. Persisting before/after patches turns HITL into training data (`scripts/export_corrections.py` → schema-aligner goldens) instead of one-off edits.

---

## 6. Background Work: SKIP LOCKED Work Queue + Kafka Consumers

**Decision:** Long-running agent jobs claim rows with Postgres `FOR UPDATE SKIP LOCKED`; DLQ and Neo4j graph sync run as in-process asyncio consumers started with the FastAPI app.

**Alternatives Evaluated:**
* Celery/RQ for every agent task.
* Separate worker deployments for each consumer.

**Why Chosen:** One service binary keeps local compose simple. `SKIP LOCKED` gives safe multi-worker claiming without Redis locks; Kafka consumers stay colocated with the API that owns the graph and DB pool.
