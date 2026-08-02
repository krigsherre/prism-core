# Agentic Brain

LangGraph Tri-Modal RAG orchestrator (SQL / Cypher / Vector) with HITL, DLQ, and durable checkpoints. Design rationale lives in [`decision.md`](./decision.md).

## Prerequisites

- Python 3.10+
- Poetry
- Postgres, Redis, Kafka, Neo4j, Qdrant (see root `docker-compose` / `.env.example`)

## Setup

```bash
poetry install
# Configure LLM keys and service URLs via repo-root `.env` (or a local `.env`)
```

## Run

```bash
PYTHONPATH=src poetry run uvicorn api.main:app --host 0.0.0.0 --port 8001 --reload
```

Docker image listens on **8001** (`Dockerfile` healthcheck: `GET /health`).

## Tests

```bash
poetry run pytest
```

With coverage (optional):

```bash
poetry run pytest --cov=src --cov-report=term-missing
```

## Layout

```text
src/
  api/           # FastAPI app, routes, auth middleware
  graph/         # LangGraph workflow + modality nodes
  tools/         # Postgres, Neo4j, Qdrant, Cube helpers
  consumers/     # DLQ, graph sync, work-queue workers
  llm/           # LLMFactory
  utils/         # HITL corrections, DLQ views
scripts/         # export_corrections → schema-aligner goldens
tests/
```
