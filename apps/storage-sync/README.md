# Storage Sync

Kafka worker that bifurcates extracted DOMs, upserts aligned rows into Postgres, dual-routes embeddings to Qdrant, and keeps vectors/views consistent via CDC. Design rationale lives in [`decision.md`](./decision.md).

## Prerequisites

- Python 3.10–3.12
- Poetry
- Kafka, Postgres, Qdrant (+ optional embeddings server); see root `docker-compose` / `.env.example`

## Setup

```bash
poetry install
```

## Run

```bash
PYTHONPATH=src poetry run python -m main
```

Migrations:

```bash
poetry run alembic upgrade head
```

## Tests

```bash
poetry run pytest
```

## Layout

```text
src/
  main.py                 # process entry: init DB/Qdrant, gather consumers
  config/                 # settings
  db/                     # models, async engine, view codegen
  repositories/           # Postgres upserts, Qdrant vectors
  kafka/
    consumers/            # bifurcation, aligned, status, DLQ, HITL, auto-promote
    cdc/                  # extracted_tables event observer → Qdrant
  proto -> packages/contracts/gen/python/proto
alembic/                  # schema migrations
tests/
```

## Env

| Variable | Required | Default | Description |
|---|---|---|---|
| `KAFKA_BROKER` | no | `localhost:9092` | Kafka bootstrap |
| `DATABASE_URL` | no | built from `POSTGRES_*` | Async Postgres URL (`postgresql+asyncpg://…`) |
| `POSTGRES_USER` / `PASSWORD` / `DB` / `HOST` / `PORT` | no | `postgres` / `postgres` / `prism` / `localhost` / `5432` | Used when `DATABASE_URL` is empty or still has `${…}` |
| `QDRANT_URL` | no | `http://localhost:6333` | Qdrant HTTP |
| `QDRANT_API_KEY` | no | `test-qdrant-key-12345` | Optional; ignored for the local test key |
| `QDRANT_COLLECTION_NAME` | no | `document_chunks` | Vector collection |
| `CDC_MAX_CONCURRENT_INFERENCES` | no | `5` | CDC observer concurrency cap |
| `CHUNK_ASSEMBLE_TIMEOUT_SECONDS` | no | `900` | DOM chunk assemble timeout |
| `SCHEMA_REGISTRY_PATH` | no | sibling / image path | `registry.json` for BI view codegen |
