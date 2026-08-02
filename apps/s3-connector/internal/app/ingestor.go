package app

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"time"

	"go.opentelemetry.io/otel"
	"go.uber.org/zap"

	"s3-connector/internal/config"
	"s3-connector/internal/domain"

	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/segmentio/kafka-go"
)

type MessageFetcher interface {
	FetchMessage(ctx context.Context) (kafka.Message, error)
	CommitMessages(ctx context.Context, msgs ...kafka.Message) error
}

type S3Getter interface {
	GetObject(ctx context.Context, bucket, key string) (*s3.GetObjectOutput, error)
}

type Cache interface {
	FilterNew(ctx context.Context, etags []string) ([]string, error)
	CacheEtags(ctx context.Context, etags []string) error
}

type DB interface {
	FindExisting(ctx context.Context, etags []string) ([]string, error)
	BulkMarkProcessed(ctx context.Context, etags []string) error
}

type GatewayClient interface {
	PostFile(ctx context.Context, tenantID, filename string, stream io.Reader) error
}

type Ingestor struct {
	KafkaReader MessageFetcher
	S3Client    S3Getter
	Cache       Cache
	DB          DB
	Gateway     GatewayClient
	Config      *config.AppConfig
}

func NewIngestor(
	kafkaReader MessageFetcher,
	s3Client S3Getter,
	cache Cache,
	db DB,
	gateway GatewayClient,
	cfg *config.AppConfig,
) *Ingestor {
	return &Ingestor{
		KafkaReader: kafkaReader,
		S3Client:    s3Client,
		Cache:       cache,
		DB:          db,
		Gateway:     gateway,
		Config:      cfg,
	}
}

func (w *Ingestor) Start(ctx context.Context) {
	zap.L().Info("Batch Ingestor worker started...")

	for {
		messages := make([]kafka.Message, 0, w.Config.MaxBatchSize)
		fetchCtx, cancel := context.WithTimeout(ctx, w.Config.FetchTimeout)

		for len(messages) < w.Config.MaxBatchSize {
			m, err := w.KafkaReader.FetchMessage(fetchCtx)
			if err != nil {
				break
			}
			messages = append(messages, m)
		}
		cancel()

		if len(messages) == 0 {
			time.Sleep(10 * time.Millisecond)
			select {
			case <-ctx.Done():
				return
			default:
				continue
			}
		}

		if err := w.ProcessBatch(ctx, messages); err != nil {
			zap.L().Error("Batch processing failed", zap.Error(err))
		} else {
			if err := w.KafkaReader.CommitMessages(ctx, messages...); err != nil {
				zap.L().Error("Failed to commit offsets", zap.Error(err))
			}
		}

		select {
		case <-ctx.Done():
			return
		default:
		}
	}
}

func (w *Ingestor) ProcessBatch(ctx context.Context, messages []kafka.Message) error {
	tracer := otel.Tracer("s3-connector")
	ctx, span := tracer.Start(ctx, "ProcessBatch")
	defer span.End()

	var allEvents []domain.S3DiscoveryEvent
	var allEtags []string

	for _, m := range messages {
		var event domain.S3DiscoveryEvent
		if err := json.Unmarshal(m.Value, &event); err == nil {
			allEvents = append(allEvents, event)
			allEtags = append(allEtags, string(event.ETag))
		}
	}

	if len(allEtags) == 0 {
		return nil
	}

	newFromCache, err := w.Cache.FilterNew(ctx, allEtags)
	if err != nil {
		return fmt.Errorf("cache check failed: %w", err)
	}
	if len(newFromCache) == 0 {
		return nil
	}

	existingInDB, err := w.DB.FindExisting(ctx, newFromCache)
	if err != nil {
		return fmt.Errorf("db check failed: %w", err)
	}

	existingMap := make(map[string]bool)
	for _, e := range existingInDB {
		existingMap[e] = true
	}

	var genuinelyNewEtags []string
	for _, event := range allEvents {
		etagStr := string(event.ETag)
		if existingMap[etagStr] {
			continue
		}

		isNew := false
		for _, e := range newFromCache {
			if e == etagStr {
				isNew = true
				break
			}
		}

		if !isNew {
			continue
		}

		zap.L().Info("Ingesting genuinely new file", zap.String("key", string(event.Key)), zap.String("tenant", string(event.TenantID)))
		genuinelyNewEtags = append(genuinelyNewEtags, etagStr)

		resp, err := w.S3Client.GetObject(ctx, string(event.Bucket), string(event.Key))
		if err != nil {
			zap.L().Error("Failed to download file", zap.String("key", string(event.Key)), zap.Error(err))
			continue
		}

		if err := w.Gateway.PostFile(ctx, string(event.TenantID), string(event.Key), resp.Body); err != nil {
			zap.L().Error("Failed to post file to gateway", zap.String("key", string(event.Key)), zap.Error(err))
		}
		resp.Body.Close()
	}

	if len(genuinelyNewEtags) > 0 {
		if err := w.DB.BulkMarkProcessed(ctx, genuinelyNewEtags); err != nil {
			zap.L().Error("Bulk DB mark failed", zap.Error(err))
		}
		if err := w.Cache.CacheEtags(ctx, genuinelyNewEtags); err != nil {
			zap.L().Error("Bulk Cache set failed", zap.Error(err))
		}
	}

	return nil
}
