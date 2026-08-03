# API Gateway

Stateless Go ingress for Prism: stream uploads to S3, publish `IngestEvent` protobufs to Kafka, return `202 Accepted`. Design rationale lives in [`decision.md`](./decision.md).

## Prerequisites

- Go 1.25+
- Access to S3 (or S3Mock) and Kafka (see root `docker-compose` / `.env.example`)

## Setup

```bash
go mod download
```

## Run

```bash
go run ./cmd/api
# or: npm run dev
```

Listens on **8080** by default (`APP_PORT`).

## Example

```bash
curl -X POST http://localhost:8080/api/v1/upload \
  -H "Authorization: Bearer <jwt>" \
  -H "X-Tenant-ID: tenant_1" \
  -F "file=@/path/to/invoice.pdf"
```

## Tests

```bash
go test -cover ./...
```

## Layout

```text
cmd/api/                 # process entrypoint
internal/
  app/                   # ingress facade (hash + S3 + Kafka)
  config/                # viper / env config
  http/                  # upload handler + middleware
  infrastructure/        # S3, Kafka, OTEL
```

## Env

| Variable | Default | Description |
|---|---|---|
| `APP_PORT` | `8080` | HTTP listen port |
| `KAFKA_BROKER` | `localhost:9092` | Kafka bootstrap |
| `KAFKA_INGESTTOPIC` | `doc_ingest_events` | Ingest event topic |
| `S3_REGION` | `me-east-1` | AWS region |
| `S3_BUCKET` | `prism-raw-documents` | Raw upload bucket |
| `S3_ENDPOINT` | _(empty)_ | Path-style endpoint for S3Mock/MinIO |
