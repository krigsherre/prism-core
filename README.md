# prism-core

Prism turns messy business documents into structured data you can query — layout-aware extraction, schema alignment with critics, and chat over Postgres / Neo4j / Qdrant.

**Project round:** [`SUBMISSION.md`](SUBMISSION.md) · **diagrams:** [`HLD.md`](HLD.md) · **umbrella ADRs:** [`decisions.md`](decisions.md)

---

## Docs map

| Doc | What it is |
|-----|------------|
| [`SUBMISSION.md`](SUBMISSION.md) | Project-round write-up |
| [`HLD.md`](HLD.md) | High-level design, diagrams, service map |
| [`decisions.md`](decisions.md) | Cross-cutting ADRs |
| [`RESEARCH.md`](RESEARCH.md) | Papers / systems mapped to design choices |
| `apps/*/README.md` + `decision.md` | Per-service runbook + ADR |
| [`infra/README.md`](infra/README.md) | ElasticMQ, S3Mock, Cube, CDC, observability |
| [`packages/contracts/README.md`](packages/contracts/README.md) | Shared Protobuf / Buf codegen |

---

## Prerequisites

- Docker + Docker Compose v2
- Go **1.25+** (ingress / workers)
- Python **3.10–3.12** + Poetry (ML / sync / brain)
- Node **20+** (optional, for `web-dashboard` locally)
- GPU optional (recommended for `gpu-extractor` / vLLM sidecars)

---

## Getting started

```bash
cp .env.example .env
make up
```

Optional sidecars (ElasticMQ, S3Mock, Cube, Kafka Connect, Grafana) — see [`infra/README.md`](infra/README.md). Do not run root and infra data stores on the same ports together.

Then:

1. UI → http://localhost:3000  
2. Upload → watch **Documents** queue  
3. HITL / DLQ when critics refuse a row  
4. **Chat** for SQL / graph / vector Q&A  

---

## Ports

| Surface | URL |
|---------|-----|
| Web dashboard | http://localhost:3000 |
| API gateway | http://localhost:8080 |
| Agentic brain | http://localhost:8001 |
| Postgres / Kafka / Redis | `5432` / `9092` / `6379` |
| Neo4j / Qdrant | http://localhost:7474 · http://localhost:6333 |

---

## Pipeline

```text
Upload → Kafka → triage → GPU DOM → align (critics / reflexion / HITL) → Postgres
                                                    ↘ dual-route / CDC → Qdrant (+ graph tasks)
Chat ← agentic-brain (SQL | Cypher | Vector)
```

Workers: `sqs-kafka-bridge` · `s3-connector` · `api-gateway` · `triage-worker` · `gpu-extractor` · `schema-aligner` · `storage-sync` · `agentic-brain` · `web-dashboard`

---

## Development & tests

```bash
# Go
cd apps/api-gateway && go test ./...
cd apps/triage-worker && go test ./...

# Python
cd apps/schema-aligner && poetry run pytest
cd apps/storage-sync && poetry run pytest

# Dashboard
cd apps/web-dashboard && npm test -- --watchAll=false
```

Goldens: `apps/schema-aligner/evals/golden/`.

---

## Repository layout

```text
apps/                 Microservices (Go + Python + Next.js)
packages/contracts/   Protobuf + Buf codegen (see packages/contracts/README.md)
infra/                Sidecar compose, Cube, logging, GPU helper scripts
docker-compose.yml    Product stack (make up)
.env.example          Canonical env template
```
