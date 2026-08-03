# Architecture Decision Record (ADR): SQS → Kafka Bridge

Foundational decisions for the `sqs-kafka-bridge` — ingress buffer from AWS SQS into internal Kafka.

---

## 1. Custom Go Worker vs Kafka Connect

**Decision:** Ship a small Go service instead of a Kafka Connect SQS source plugin.

**Alternatives Evaluated:**
* Kafka Connect + AWS SQS / Camel connector (JVM).

**Why Chosen:** Keeps the stack Go/Python-only, avoids Connect classpath/JAR ops, and lets me control OTEL injection and payload shaping at the edge. Trade-off: one more binary to own.

---

## 2. Delete-After-Kafka-ACK

**Decision:** Never call SQS `DeleteMessage` until `WriteMessages` succeeds.

**Why Chosen:** If Kafka is down, the message stays invisible until the visibility timeout and reappears for retry — no silent drop. Combined with `SIGTERM`/`SIGINT` cancellation, in-flight batches finish before exit.

---

## 3. Clean `cmd/` + `internal/` Layout

**Decision:** Split entrypoint, config, SQS adapter, Kafka producer, and orchestration behind interfaces.

**Why Chosen:** Unit tests mock SQS/Kafka and assert “no delete on publish failure” without ElasticMQ.

---

## 4. Downstream Deduplication (Not Here)

**Decision:** Do not keep local bloom/idempotency state in the bridge.

**Why Chosen:** SQS is at-least-once; duplicates are expected. `s3-connector` already locks on etag via Redis. Keeping the bridge stateless avoids another failure mode at the edge.
