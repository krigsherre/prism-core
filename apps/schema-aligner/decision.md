# Architecture Decision Record (ADR): Schema Aligner

Foundational decisions for the `schema-aligner` service — structured extraction onto registered schemas, fail-closed critics, and critic-guided Reflexion.

---

## 1. Structured Outputs via Instructor + Dynamic Pydantic

**Decision:** Build per-table response models with `pydantic.create_model` from `registry.json`, and extract via `instructor` (Anthropic by default; OpenAI-compatible / vLLM optional).

**Alternatives Evaluated:**
* Free-form JSON mode + retry parsers.
* Local logit-masking (`outlines`) tied to a single inference runtime.

**Why Chosen:** Schemas differ by document type. Dynamic models keep the registry as the source of truth. Instructor gives typed retries without locking the worker to one GPU stack. Trade-off: weaker than true FSM masking, mitigated by critics + Reflexion.

---

## 2. Kafka Concurrency with a Semaphore

**Decision:** Cap in-flight alignments with `asyncio.Semaphore(max_concurrent_inferences)` on the raw-table consumer; keep CDC consumers light.

**Why Chosen:** LLM calls are the bottleneck. Bounding concurrency protects rate limits and memory while the event loop continues heartbeats and CDC updates.

---

## 3. Row-Oriented Chunking

**Decision:** Slice large tables into `CHUNK_SIZE_ROWS` (default 10) and extract arrays of row objects, then merge.

**Alternatives Evaluated:**
* Columnar parallel arrays.
* One-shot full-table prompts.

**Why Chosen:** Avoids column-length drift and “lost in the middle” on long tables. The coordinator merges chunks in Python.

---

## 4. Heuristic Orientation + Context Injection

**Decision:** Detect transposed (vertical) tables via header/value ∩ schema heuristics; inject shared context fields (`context_currency`, `context_scale`, …) before model compile.

**Why Chosen:** Financial statements are often pivoted; forcing the LLM to transpose in-place hallucinates. Keeping entity/scale out of every registry entry stays DRY.

---

## 5. Declarative Critic Packs + Structured Results

**Decision:** Domain packs under `core/packs/` drive a rule engine emitting `CriticResult` (`rule_id`, HARD/SOFT/INFO, expected/actual, hints). Incomplete identity sides fail closed; scale-aware tolerances use `context_scale`.

**Why Chosen:** Free-text “logic error” strings were opaque to Reflexion/HITL. Structured rule IDs make repair prompts and dashboards deterministic.

---

## 6. Critic-Guided Reflexion Before DLQ/HITL

**Decision:** On HARD critic failures, run a bounded in-process repair loop (`max_reflexion_attempts`) with tiered prompts, then escalate to DLQ/HITL with a reflexion trail.

**Why Chosen:** Many failures are local (wrong scale, swapped columns). Burning Kafka retries for those is wasteful; structured critic feedback enables targeted repairs first.
