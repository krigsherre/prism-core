package app

import (
	"context"
	"encoding/json"
	"fmt"
	"runtime/debug"
	"time"

	prismv1 "contracts/gen/go/proto/prism/v1"
	"triage-worker/internal/app/pipeline"
	"triage-worker/internal/app/routing"
	"triage-worker/internal/config"
	"triage-worker/internal/infrastructure/kafka"
	"triage-worker/internal/infrastructure/redis"

	kafka_go "github.com/segmentio/kafka-go"
	"go.opentelemetry.io/otel"
	"go.uber.org/zap"
	"google.golang.org/protobuf/proto"
)

type TriageWorker struct {
	logger          *zap.Logger
	consumer        kafka.Consumer
	dlqProducer     kafka.Producer
	gpuProducer     kafka.Producer
	statusProducer  kafka.Producer
	cleanupProducer kafka.Producer
	cache           redis.DedupCache
	dedupChain      pipeline.DedupHandler
	gpuStrategy     routing.RoutingStrategy
	cfg             *config.AppConfig
}

func NewTriageWorker(logger *zap.Logger, consumer kafka.Consumer, dlqProducer kafka.Producer, gpuProducer kafka.Producer, statusProducer kafka.Producer, cleanupProducer kafka.Producer, cache redis.DedupCache, cfg *config.AppConfig) *TriageWorker {
	exact := pipeline.NewExactHashHandler(cache)
	minhash := pipeline.NewMinHashLSHHandler(cache)
	exact.SetNext(minhash)

	return &TriageWorker{
		logger:          logger,
		consumer:        consumer,
		dlqProducer:     dlqProducer,
		gpuProducer:     gpuProducer,
		statusProducer:  statusProducer,
		cleanupProducer: cleanupProducer,
		cache:           cache,
		dedupChain:      exact,
		gpuStrategy:     routing.NewGpuRouteStrategy(gpuProducer),
		cfg:             cfg,
	}
}

func (w *TriageWorker) Start(ctx context.Context) {
	w.logger.Info("Starting worker pool", zap.Int("goroutines", w.cfg.Concurrency))
	sem := make(chan struct{}, w.cfg.Concurrency)

	for {
		select {
		case <-ctx.Done():
			w.logger.Info("Context cancelled, shutting down triage worker gracefully...")
			return
		default:
			msg, err := w.consumer.FetchMessage(ctx)
			if err != nil {
				w.logger.Error("Failed to fetch message", zap.Error(err))
				time.Sleep(time.Second)
				continue
			}

			sem <- struct{}{}
			go func(m kafka_go.Message) {
				defer func() { <-sem }()
				w.processMessage(ctx, m)
			}(msg)
		}
	}
}

func (w *TriageWorker) processMessage(ctx context.Context, msg kafka_go.Message) {
	tracer := otel.Tracer("triage-worker")
	ctx, span := tracer.Start(ctx, "processMessage")
	defer span.End()

	var event prismv1.IngestEvent

	defer func() {
		if r := recover(); r != nil {
			w.logger.Error("PANIC recovered", zap.Int64("offset", msg.Offset), zap.Any("panic", r), zap.String("stack", string(debug.Stack())))
			w.handleFailure(ctx, msg, &event, fmt.Sprintf("Panic: %v", r))
		}
	}()

	if err := proto.Unmarshal(msg.Value, &event); err != nil {
		w.logger.Error("Failed to unmarshal message", zap.Error(err))
		w.handleFailure(ctx, msg, nil, "Failed to unmarshal message")
		return
	}

	res, err := w.dedupChain.Handle(ctx, &event)
	if err != nil {
		w.logger.Error("Dedup pipeline error", zap.String("eventId", event.EventId), zap.Error(err))
		w.handleFailure(ctx, msg, &event, err.Error())
		return
	}

	switch res {
	case pipeline.ResultExactDuplicate:
		w.handleExactDuplicate(ctx, msg, &event)
	case pipeline.ResultVersionUpdate:
		w.handleVersionUpdate(ctx, msg, &event)
	case pipeline.ResultNewDocument:
		w.handleNewDocument(ctx, msg, &event)
	default:
		w.logger.Error("Unknown dedup result, dropping message", zap.Any("res", res))
		w.commitMessage(ctx, msg)
	}
}

func (w *TriageWorker) handleExactDuplicate(ctx context.Context, msg kafka_go.Message, event *prismv1.IngestEvent) {
	w.logger.Info("Dropping exact duplicate", zap.String("eventId", event.EventId))

	w.commitMessage(ctx, msg)
	w.publishStatus(ctx, event, "DUPLICATE", "Exact duplicate dropped")

	if w.cleanupProducer != nil {
		cleanupPayload, err := json.Marshal(map[string]string{"s3_uri": event.S3Uri})
		if err != nil {
			w.logger.Error("Failed to marshal s3 cleanup payload", zap.Error(err))
		} else if err := w.cleanupProducer.PublishMessage(ctx, []byte(event.EventId), cleanupPayload); err != nil {
			w.logger.Error("Failed to publish to s3_cleanup_tasks", zap.Error(err))
		}
	}
}

func (w *TriageWorker) handleNewDocument(ctx context.Context, msg kafka_go.Message, event *prismv1.IngestEvent) {
	w.logger.Info("Processing new document", zap.String("eventId", event.EventId))

	err := w.gpuStrategy.Route(ctx, event)
	if err != nil {
		w.logger.Error("Routing strategy failed", zap.String("eventId", event.EventId), zap.Error(err))
		w.handleFailure(ctx, msg, event, err.Error())
		return
	}

	w.publishStatus(ctx, event, "IN_PROGRESS", "")
	w.commitMessage(ctx, msg)
}

func (w *TriageWorker) handleVersionUpdate(ctx context.Context, msg kafka_go.Message, event *prismv1.IngestEvent) {
	w.logger.Info("Emitting tombstone for version update", zap.String("eventId", event.EventId))

	err := w.gpuStrategy.Route(ctx, event)
	if err != nil {
		w.logger.Error("Routing strategy failed", zap.String("eventId", event.EventId), zap.Error(err))
		w.handleFailure(ctx, msg, event, err.Error())
		return
	}

	w.publishStatus(ctx, event, "IN_PROGRESS", "")
	w.commitMessage(ctx, msg)
}

func (w *TriageWorker) publishStatus(ctx context.Context, event *prismv1.IngestEvent, status, errMsg string) {
	if event == nil {
		return
	}

	filename := "unknown"
	if event.Metadata != nil {
		if fn, ok := event.Metadata["original_filename"]; ok {
			filename = fn
		}
	}

	statusPayload, err := json.Marshal(map[string]string{
		"document_id":   event.EventId,
		"tenant_id":     event.TenantId,
		"filename":      filename,
		"current_stage": "triage-worker",
		"status":        status,
		"error_message": errMsg,
		"updated_at":    time.Now().Format(time.RFC3339),
	})
	if err != nil {
		w.logger.Error("Failed to marshal status event", zap.Error(err))
		return
	}

	_ = w.statusProducer.PublishMessage(ctx, []byte(event.TenantId), statusPayload)
}

func (w *TriageWorker) handleFailure(ctx context.Context, msg kafka_go.Message, event *prismv1.IngestEvent, errMsg string) {
	eventID := "unknown"
	if event != nil {
		eventID = event.EventId
	}

	failKey := fmt.Sprintf("dlq:failcount:%s", eventID)
	count, _ := w.cache.Incr(ctx, failKey)

	if count >= int64(w.cfg.MaxRetries) {
		w.logger.Error("Message failed max retries, routing to DLQ and ACKing original", zap.String("eventId", eventID), zap.Int64("failures", count))
		if err := w.dlqProducer.PublishMessage(ctx, msg.Key, msg.Value); err != nil {
			w.logger.Error("Failed to write to DLQ", zap.Error(err))
			return
		}
		w.publishStatus(ctx, event, "FAILED", errMsg)
		w.commitMessage(ctx, msg)
	} else {
		w.logger.Warn("Message failed, will retry", zap.String("eventId", eventID), zap.Int64("failures", count))
	}
}

func (w *TriageWorker) commitMessage(ctx context.Context, msg kafka_go.Message) {
	err := w.consumer.CommitMessages(ctx, msg)
	if err != nil {
		w.logger.Error("Failed to commit message", zap.Error(err), zap.Int64("offset", msg.Offset), zap.String("topic", msg.Topic))
	}
}
