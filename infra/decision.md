# Architecture Decision Record (ADR): Infra

Foundational decisions for local shared infrastructure — data plane sidecars, BI, CDC registration, and observability.

---

## 1. Root Compose Owns Apps; Infra Owns Sidecars

**Decision:** Product workers/UI start from the repo-root `docker-compose.yml` (`make up`). `infra/docker-compose.yml` carries ElasticMQ, S3Mock, Kafka Connect, Cube.js, and the Loki/Tempo/Grafana/OTEL stack (plus a self-contained data plane for infra-only demos).

**Alternatives Evaluated:**
* One mega-compose with every sidecar always on.
* Duplicate app services inside `infra/` (gateway, connector, bridge).

**Why Chosen:** Keeps day-1 bring-up focused on the product path. Ops/BI/CDC extras stay optional. Duplicating Go apps under `infra/` drifted passwords and build contexts — those services were removed from the infra file.

---

## 2. ElasticMQ Instead of Real AWS SQS Locally

**Decision:** Run SoftwareMill ElasticMQ with `elasticmq.conf` queue `s3_event_queue` for `sqs-kafka-bridge`.

**Why Chosen:** Same SQS API surface without AWS credentials or LocalStack weight. Bridge points `SQS_ENDPOINT` / `SQS_QUEUE_URL` at ElasticMQ in `.env`.

---

## 3. S3Mock + Init One-Shot

**Decision:** Adobe S3Mock for object storage locally; `s3mock-init` creates expected buckets on start.

**Why Chosen:** Avoids LocalStack scripts that went missing from `infra/scripts/`. Gateway/connector talk to `S3_ENDPOINT=http://s3mock:9090`.

---

## 4. Registry-Driven Cube Models

**Decision:** `cube/generate_cubes.py` reads `apps/schema-aligner/src/core/registry.json` and emits YAML cubes over Postgres `view_*` relations; `cube.js` injects `tenant_id` filters from the security context.

**Why Chosen:** BI dimensions stay in lockstep with aligner schemas and storage-sync views. Tenant rewrite prevents cross-tenant Cube queries in shared demos.

---

## 5. Debezium via Kafka Connect (Opt-In)

**Decision:** Ship `kafka-connect/register-debezium.json` for `public.extracted_tables` with `pgoutput` and `wal_level=logical` on the infra Postgres.

**Why Chosen:** Feeds CDC-style topics for `storage-sync` observers without baking Connect into the default root stack. Registration stays a deliberate `curl` so Connect can boot before the connector exists.

---

## 6. OTEL → Tempo, Logs → Loki, UI → Grafana

**Decision:** Collector receives OTLP (`4317`/`4318`), exports traces to Tempo; Promtail/Loki handle container logs; Grafana provisions both datasources.

**Why Chosen:** Matches Go workers that already emit OTEL spans. Keeps local debugging one Grafana hop away without a cloud APM dependency.
