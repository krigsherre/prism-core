# Architecture Decision Record (ADR): Contracts

Foundational decisions for shared Prism wire formats across Go, Python, and TypeScript.

---

## 1. Protobuf as the Cross-Language Contract

**Decision:** Define Kafka/binary payloads in `proto/prism/v1/*.proto` and generate stubs with Buf into `gen/{go,python,ts}`.

**Alternatives Evaluated:**
* Hand-written JSON DTOs per language.
* gRPC service stubs for every hop (heavy for fire-and-forget Kafka).

**Why Chosen:** `IngestEvent` and `DocumentDOM` cross Go ingress and Python GPU/sync workers. One schema + codegen avoids silent field drift. Kafka stays protobuf bytes; HTTP/JSON APIs can still use companion JSON Schemas under `schemas/`.

---

## 2. Commit Generated Code

**Decision:** Check in `gen/` outputs (and `gen/go/go.mod`) rather than generating only in CI/Docker.

**Why Chosen:** App Dockerfiles and local `go test` / Poetry installs work offline without Buf plugins. Trade-off: PRs that change `.proto` must also refresh `gen/`.

---

## 3. Buf for Lint, Breaking, and Plugins

**Decision:** Use `buf.yaml` DEFAULT lint + FILE breaking, and remote plugins (`protocolbuffers/{go,python,pyi}`, `bufbuild/es`).

**Why Chosen:** Consistent style and an explicit breaking gate before merging contract changes that would brick consumers.

---

## 4. Go Module Path `contracts/gen/go`

**Decision:** Generated Go lives under module path `contracts/gen/go` with monorepo `replace` directives from each Go app.

**Why Chosen:** Keeps import paths stable (`contracts/gen/go/proto/prism/v1`) without publishing a private module registry for the project round.

---

## 5. JSON Schema Sidecars for Non-Protobuf Events

**Decision:** Keep draft-07 schemas (e.g. `AlignedSQLPayload`) beside protos for JSON Kafka/HTTP shapes that never needed protobuf.

**Why Chosen:** Aligner’s row payloads and synonym maps are JSON-native; forcing them through protobuf would add churn without a binary consumer benefit.
