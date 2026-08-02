# Web Dashboard

Next.js App Router UI for Prism: chat/RAG, documents, HITL, DLQ, and agent task surfaces against `agentic-brain` + `api-gateway`. Design rationale lives in [`decision.md`](./decision.md).

## Prerequisites

- Node 20+
- Running `agentic-brain` (and `api-gateway` for uploads); see root `docker-compose` / `.env.example`

## Setup

```bash
npm install
```

## Run

```bash
npm run dev
```

Production:

```bash
npm run build && npm start
```

## Tests

```bash
npm test -- --watchAll=false
```

## Layout

```text
app/                 # App Router pages (chat, documents, hitl, dlq, agents)
components/          # shared layout + UI primitives
features/            # domain UI + hooks per surface
services/            # API client (NEXT_PUBLIC_API_URL)
store/               # zustand stores
lib/                 # utils
public/
```

## Env

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Agentic Brain HTTP base (baked at **build** time) |
| `NEXT_PUBLIC_GATEWAY_URL` | `http://localhost:8080` | API Gateway upload URL (baked at **build** time) |
| `WEB_DASHBOARD_PORT` | `3000` | Host port in compose |

For Docker, pass the `NEXT_PUBLIC_*` values as compose build args (see root `docker-compose.yml`). Rebuild the image after changing them.
