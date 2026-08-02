# Architecture Decision Record (ADR): Web Dashboard

Foundational decisions for the Prism operator UI — Next.js App Router against brain + gateway APIs.

---

## 1. Next.js App Router + Standalone Output

**Decision:** Ship a Next 14 App Router app with `output: "standalone"` for a slim Node runtime image.

**Alternatives Evaluated:**
* CRA/Vite SPA behind a separate reverse proxy.
* Server-heavy BFF in this repo.

**Why Chosen:** File-based routes match product surfaces (`/chat`, `/documents`, `/hitl`, `/dlq`, `/agents`). Standalone output keeps the compose image small without embedding a full `node_modules` tree at runtime.

---

## 2. Feature Folders Over a Flat `components/` Dump

**Decision:** Keep domain UI under `features/{chat,documents,hitl,dlq,agents,pdf}` with shared primitives in `components/ui` and shell chrome in `components/layout`.

**Why Chosen:** Each ops surface owns its hooks/tests without coupling chat state to DLQ tables. Shared shadcn-style primitives stay generic.

---

## 3. Dual Backend Clients (Brain + Gateway)

**Decision:** Browser calls `NEXT_PUBLIC_API_URL` (agentic-brain) for chat/agents/HITL/DLQ, and `NEXT_PUBLIC_GATEWAY_URL` for multipart document upload.

**Why Chosen:** Upload streaming and Kafka fan-out belong on the Go gateway; conversational/agent APIs belong on the Python brain. One env-split avoids stuffing uploads through the brain.

---

## 4. TanStack Query + Zustand

**Decision:** Server state via React Query; light UI/session chrome via Zustand toasts/stores.

**Why Chosen:** Query caching/refetch fits polling document/HITL lists; Zustand avoids prop-drilling toast and sidebar chrome. Trade-off: two state libraries — scoped so Query owns network data.

---

## 5. Alpine Multi-Stage Docker Image

**Decision:** `node:20-alpine` build → copy standalone server + static assets into a slim runner. Pass `NEXT_PUBLIC_API_URL` / `NEXT_PUBLIC_GATEWAY_URL` as build args so the client bundle is baked correctly.

**Why Chosen:** Matches compose `context: ./apps/web-dashboard` and keeps GPU/Python deps out of the UI image. Next inlines `NEXT_PUBLIC_*` at build time, so runtime `env_file` alone is not enough for browser calls.
