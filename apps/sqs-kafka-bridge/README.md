# SQS → Kafka Bridge

Long-polls AWS SQS (or ElasticMQ), forwards S3 notification payloads to Kafka `s3_discovery_events`, then deletes from SQS only after Kafka ACK. Design rationale lives in [`decision.md`](./decision.md).

## Prerequisites

- Go 1.25+
- Kafka + SQS/ElasticMQ (see root `docker-compose` / `.env.example`)

## Setup

```bash
go mod download
```

## Run

```bash
go run ./cmd/bridge
```

## Tests

```bash
go test -cover ./...
```

## Layout

```text
cmd/bridge/                 # entrypoint + graceful shutdown
internal/
  app/                      # poll → publish → delete loop
  config/                   # viper / env
  infrastructure/aws/       # SQS adapter
  infrastructure/kafka/     # Kafka producer
```

## Env

| Variable | Required | Default | Description |
|---|---|---|---|
| `SQS_QUEUE_URL` | yes | — | Full SQS queue URL |
| `KAFKA_BROKER` | yes | — | Kafka bootstrap |
| `KAFKA_TOPIC` | no | `s3_discovery_events` | Destination topic |
| `AWS_REGION` | no | `us-east-1` | AWS region |
| `SQS_ENDPOINT` | no | _(empty)_ | Override for ElasticMQ |
| `APP_MAXMESSAGES` | no | `10` | Max messages per receive |
| `AWS_WAITTIMESECONDS` | no | `20` | SQS long-poll wait |
