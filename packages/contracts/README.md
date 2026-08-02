# Contracts

Shared Protobuf definitions and generated stubs for Prism (Go, Python, TypeScript), plus a few JSON Schemas for Kafka/JSON payloads. Design rationale lives in [`decision.md`](./decision.md).

## Prerequisites

- Node 20+ (Buf CLI via `@bufbuild/buf`)
- Network access to Buf Schema Registry plugins on first generate

## Layout

```text
proto/prism/v1/     # source of truth (.proto)
  events.proto      # IngestEvent, CitationPayload
  dom.proto         # DocumentDOM / Node / NodeType
  state.proto       # AgentState
schemas/            # JSON Schema companions (aligned SQL, synonyms)
buf.yaml            # lint / breaking
buf.gen.yaml        # Go + Python + TS plugins
gen/
  go/               # module contracts/gen/go (apps replace this path)
  python/           # prism_contracts package (Poetry path deps)
  ts/               # @bufbuild generated TS
```

## Setup

```bash
npm install
```

## Generate

```bash
npm run generate
# or: npx buf generate
```

Commit regenerated `gen/**` when protos change so Go/Python apps build without a Buf toolchain.

## Consumers

| Language | How apps depend |
|---|---|
| Go | `replace contracts/gen/go => ../../packages/contracts/gen/go` (`api-gateway`, `triage-worker`, …) |
| Python | Poetry path / `PYTHONPATH` → `gen/python` (`gpu-extractor`, `storage-sync`, …) |
| TypeScript | Import from `gen/ts` when needed |

## Lint / breaking

```bash
npx buf lint
npx buf breaking --against '.git#branch=main'
```
