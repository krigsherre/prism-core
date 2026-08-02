# Triage Worker

Kafka worker that dedupes ingest events (exact hash + version-update chain), routes new work to `gpu_processing_queue`, and escalates poison pills to DLQ after Redis-backed retries. Design rationale lives in [`decision.md`](./decision.md).

## Prerequisites

- Go 1.25+
- Kafka + Redis (see root `docker-compose` / `.env.example`)
- Generated Go contracts under `packages/contracts/gen/go` (module replace)

## Setup

```bash
go mod download
```

## Run

```bash
go run ./cmd/worker
```

## Tests

```bash
go test -cover ./...
```

## Layout

```text
cmd/worker/                 # entrypoint + graceful shutdown
internal/
  app/                      # worker pool + message lifecycle
    pipeline/               # exact-hash → version-update chain
    routing/                # GPU topic publish strategy
  config/                   # viper / env
  infrastructure/
    kafka/                  # consumer + producers
    redis/                  # dedupe + fail-count cache
```

## Env

| Variable | Default | Description |
|---|---|---|
| `KAFKA_BROKER` | `localhost:9092` | Kafka bootstrap |
| `KAFKA_CONSUMERGROUP` | `triage-worker-group` | Consumer group |
| `KAFKA_INGESTTOPIC` | `doc_ingest_events` | Ingest protobuf topic |
| `KAFKA_DLQTOPIC` | `doc_dlq` | Dead-letter topic |
| `KAFKA_GPUTOPIC` | `gpu_processing_queue` | GPU extractor topic |
| `REDIS_ADDR` | `localhost:6379` | Dedup + retry counters |
| `APP_CONCURRENCY` | `100` | In-flight goroutine cap |
| `APP_MAXRETRIES` | `3` | Failures before DLQ |

Also publishes to fixed topics `document_status_events` and `s3_cleanup_tasks` (duplicate drops).
