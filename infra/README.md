# Infra

Shared local infrastructure for Prism: data stores sidecars, ElasticMQ, S3Mock, Kafka Connect (Debezium), Cube.js models, and the Loki/Tempo/Grafana/OTEL stack. Product microservices live under `apps/` and are started from the **root** `docker-compose.yml` (`make up`).

Design rationale lives in [`decision.md`](./decision.md).

## Prerequisites

- Docker / Docker Compose
- Root `.env` from `.env.example` (Postgres password defaults to `postgres`)

## Layout

```text
docker-compose.yml          # data plane + observability (+ ElasticMQ / S3Mock / Cube / Connect)
elasticmq.conf              # local SQS-compatible queues
kafka-connect/              # Debezium connector registration payload
cube/                       # Cube.js config + generated YAML models
  generate_cubes.py         # registry.json → model/cubes/*.yml
logging/                    # Loki, Promtail, Tempo, OTEL collector, Grafana datasources
scripts/                    # optional GPU sidecars (Layout Heron, Lightning vLLM)
```

## Run

Product stack (apps + core stores):

```bash
# from repo root
make up
```

Infra extras (ElasticMQ, S3Mock, Cube, Kafka Connect, observability):

```bash
# from repo root
docker compose -f infra/docker-compose.yml up -d
```

Register Debezium against the infra Postgres (after Connect is healthy):

```bash
curl -X POST http://localhost:8083/connectors \
  -H 'Content-Type: application/json' \
  -d @infra/kafka-connect/register-debezium.json
```

Regenerate Cube models from the schema registry:

```bash
python3 infra/cube/generate_cubes.py
```

## Ports (infra compose)

| Service | Host ports |
|---|---|
| Postgres | `5432` |
| Kafka | `9092`, `29092` |
| Kafka Connect | `8083` |
| Qdrant | `6333`, `6334` |
| Neo4j | `7474`, `7687` |
| Redis | `6379` |
| S3Mock | `9090` |
| ElasticMQ | `9324`, `9325` |
| Cube | `4000` (API), `4001` (dev UI) |
| Loki / Tempo / Grafana / OTEL | `3100` / `3200` / `3001` / `4317`–`4318` |

## Notes

- Do **not** run root compose and `infra/docker-compose.yml` Postgres/Kafka/Qdrant/Neo4j/Redis at the same time on the same host ports — pick one data plane.
- Qdrant collections are created by `storage-sync` on startup; S3Mock buckets are created by the `s3mock-init` one-shot service.
