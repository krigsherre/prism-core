# S3 Connector

Kafka consumer that ingests external S3 object notifications: batch-dedupe (Redis + Postgres), stream objects through `api-gateway`. Upstream SQS → Kafka handoff is owned by `sqs-kafka-bridge`. Design rationale lives in [`decision.md`](./decision.md).

## Prerequisites

- Go 1.25+
- Kafka, Redis, Postgres, reachable `api-gateway` (see root `docker-compose` / `.env.example`)

## Setup

```bash
go mod download
```

## Run

```bash
go run ./cmd/ingestor
```

## Tests

```bash
go test -cover ./...
```

## Layout

```text
cmd/ingestor/            # process entrypoint
internal/
  app/                   # batch ingest orchestration
  config/                # viper / env config
  domain/                # S3 discovery event types
  infrastructure/        # Kafka, S3, Redis, Postgres, gateway HTTP
```

## Env

| Variable | Default | Description |
|---|---|---|
| `KAFKA_BROKER` | `localhost:9092` | Kafka bootstrap |
| `KAFKA_TOPIC` | `s3_discovery_events` | Discovery topic |
| `KAFKA_GROUPID` | `ingestor_group` | Consumer group |
| `REDIS_ADDR` | `localhost:6379` | Locks + etag cache |
| `POSTGRES_DSN` | `postgres://…` | Durable etag store |
| `GATEWAY_URL` | `http://localhost:8080/api/v1/upload` | Internal upload API |
| `S3_ENDPOINT` | _(empty)_ | Path-style endpoint for S3Mock/MinIO |
| `APP_MAXBATCHSIZE` | `500` | Max Kafka messages per batch |
