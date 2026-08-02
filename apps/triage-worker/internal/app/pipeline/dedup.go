package pipeline

import (
	"context"
	"fmt"
	"log"

	prismv1 "contracts/gen/go/proto/prism/v1"
	"triage-worker/internal/infrastructure/redis"
)

type DedupResult int

const (
	ResultNewDocument DedupResult = iota
	ResultExactDuplicate
	ResultVersionUpdate
)

type DedupHandler interface {
	SetNext(handler DedupHandler) DedupHandler
	Handle(ctx context.Context, event *prismv1.IngestEvent) (DedupResult, error)
}

type BaseHandler struct {
	next DedupHandler
}

func (h *BaseHandler) SetNext(next DedupHandler) DedupHandler {
	h.next = next
	return next
}

func (h *BaseHandler) HandleNext(ctx context.Context, event *prismv1.IngestEvent) (DedupResult, error) {
	if h.next != nil {
		return h.next.Handle(ctx, event)
	}
	return ResultNewDocument, nil
}

type ExactHashHandler struct {
	BaseHandler
	cache redis.DedupCache
}

func NewExactHashHandler(cache redis.DedupCache) *ExactHashHandler {
	return &ExactHashHandler{cache: cache}
}

func (h *ExactHashHandler) Handle(ctx context.Context, event *prismv1.IngestEvent) (DedupResult, error) {
	key := fmt.Sprintf("doc:hash:%s", event.FileHashSha256)
	exists, err := h.cache.Exists(ctx, key)
	if err != nil {
		return ResultNewDocument, err
	}

	if exists {
		log.Printf("[ExactHash] Found duplicate for hash %s", event.FileHashSha256)
		return ResultExactDuplicate, nil
	}

	h.cache.Set(ctx, key, event.EventId, 0)

	return h.HandleNext(ctx, event)
}

type MinHashLSHHandler struct {
	BaseHandler
	cache redis.DedupCache
}

func NewMinHashLSHHandler(cache redis.DedupCache) *MinHashLSHHandler {
	return &MinHashLSHHandler{cache: cache}
}

func (h *MinHashLSHHandler) Handle(ctx context.Context, event *prismv1.IngestEvent) (DedupResult, error) {
	if event.Metadata != nil && event.Metadata["is_version_update"] == "true" {
		log.Printf("[MinHashLSH] Semantic version update detected for tenant %s", event.TenantId)
		return ResultVersionUpdate, nil
	}

	return h.HandleNext(ctx, event)
}
