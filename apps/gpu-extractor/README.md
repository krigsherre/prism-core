# GPU Extractor

Async document extraction worker: Kafka ingest → preprocess → layout → GPU/VLM table OCR → `DocumentDOM` protobuf fan-out. Design rationale lives in [`decision.md`](./decision.md).

## Prerequisites

- Python 3.10–3.12
- Poetry
- Kafka, S3 (or S3Mock), optional Gotenberg / vLLM sidecars (see root `docker-compose` / `.env.example`)

## Setup

```bash
poetry install
```

## Run

```bash
PYTHONPATH=src poetry run uvicorn main:app --host 0.0.0.0 --port 8000
```

Health: `GET /healthz`, readiness: `GET /readyz`.

## Tests

```bash
poetry run pytest
```

## Layout

```text
src/
  main.py            # FastAPI app + lifespan (Kafka + batcher)
  api/               # health routes
  broker/            # Kafka consumers, S3 cleanup
  config/            # settings
  core/
    engine.py        # DynamicBatcher
    service.py       # extraction orchestration
    dom/             # preprocess, chunk, post-process, table JSON
    ml/              # layout slicer, extractor adapters
  proto -> packages/contracts/gen/python/proto
tests/
```
