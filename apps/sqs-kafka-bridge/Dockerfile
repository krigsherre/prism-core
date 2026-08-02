FROM golang:1.25 AS builder

WORKDIR /app

COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download

COPY . .
RUN --mount=type=cache,target=/root/.cache/go-build \
    --mount=type=cache,target=/go/pkg/mod \
    CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /bridge ./cmd/bridge

FROM gcr.io/distroless/static-debian11

COPY --from=builder /bridge /bridge

ENTRYPOINT ["/bridge"]
