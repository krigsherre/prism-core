FROM golang:1.25 AS builder

WORKDIR /app

COPY packages/contracts/gen/go packages/contracts/gen/go

WORKDIR /app/apps/api-gateway
COPY apps/api-gateway/go.mod apps/api-gateway/go.sum ./
ENV GOPROXY=https://proxy.golang.org,direct
RUN --mount=type=cache,target=/go/pkg/mod go mod download

COPY apps/api-gateway/ .

RUN --mount=type=cache,target=/root/.cache/go-build \
    --mount=type=cache,target=/go/pkg/mod \
    CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o bin/api-gateway ./cmd/api

FROM gcr.io/distroless/static-debian11

COPY --from=builder /app/apps/api-gateway/bin/api-gateway /api-gateway

EXPOSE 8080
ENTRYPOINT ["/api-gateway"]
