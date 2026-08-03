FROM golang:1.25-bookworm AS builder

WORKDIR /app

COPY packages/contracts/gen/go packages/contracts/gen/go

WORKDIR /app/apps/triage-worker
COPY apps/triage-worker/go.mod apps/triage-worker/go.sum ./
ENV GOPROXY=https://proxy.golang.org,direct
RUN --mount=type=cache,target=/go/pkg/mod go mod download

COPY apps/triage-worker/ .

RUN --mount=type=cache,target=/root/.cache/go-build \
    --mount=type=cache,target=/go/pkg/mod \
    CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /triage-worker ./cmd/worker

FROM gcr.io/distroless/static-debian11

COPY --from=builder /triage-worker /triage-worker

ENTRYPOINT ["/triage-worker"]
