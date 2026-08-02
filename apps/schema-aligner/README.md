# Schema Aligner

Kafka worker that maps extracted tables onto registered schemas: structured LLM alignment, declarative critics, in-process Reflexion, then promote / DLQ / HITL. Design rationale lives in [`decision.md`](./decision.md).

## Prerequisites

- Python 3.10–3.12
- Poetry
- Kafka + LLM credentials (see root `.env.example`)

## Setup

```bash
poetry install
```

## Run

```bash
PYTHONPATH=src poetry run uvicorn main:app --host 0.0.0.0 --port 8001
```

## Tests

```bash
poetry run pytest
```

Evals (goldens under `evals/golden/`):

```bash
PYTHONPATH=src poetry run python evals/run_eval.py
```

## Layout

```text
src/
  main.py              # FastAPI + Kafka consumer lifespan
  api/                 # health / ops routes
  config/              # settings
  kafka/               # schema CDC, dictionary CDC, raw table DOM
  core/
    alignment.py       # WaterfallAlignmentStrategy
    verification.py    # critics
    rule_engine.py     # declarative packs
    reflexion.py       # repair loop
    doc_router.py      # deterministic routing
    registry.json      # schema registry
    packs/             # domain critic packs
evals/                 # goldens + runners
tests/
```
