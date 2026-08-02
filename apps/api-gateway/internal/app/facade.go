package app

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"time"

	"api-gateway/internal/infrastructure/kafka"
	"api-gateway/internal/infrastructure/s3"
	prismv1 "contracts/gen/go/proto/prism/v1"
	"github.com/google/uuid"
	"go.opentelemetry.io/otel"
	"go.uber.org/zap"
)

type IngressFacade interface {
	ProcessUpload(ctx context.Context, tenantID string, filename string, stream io.Reader) error
}

type ingressFacade struct {
	s3    s3.Uploader
	kafka kafka.Publisher
}

func NewIngressFacade(s3Client s3.Uploader, kafkaClient kafka.Publisher) IngressFacade {
	return &ingressFacade{s3: s3Client, kafka: kafkaClient}
}

func (f *ingressFacade) ProcessUpload(ctx context.Context, tenantID string, filename string, stream io.Reader) error {
	tracer := otel.Tracer("api-gateway")
	ctx, span := tracer.Start(ctx, "ProcessUpload")
	defer span.End()

	hasher := sha256.New()
	teeReader := io.TeeReader(stream, hasher)

	objectKey := fmt.Sprintf("%s/%d-%s-%s", tenantID, time.Now().Unix(), uuid.New().String()[:8], filename)

	span.AddEvent("starting S3 upload")
	zap.L().Info("Starting S3 upload", zap.String("tenant_id", tenantID), zap.String("object_key", objectKey))
	s3URI, err := f.s3.UploadStream(ctx, objectKey, teeReader)
	if err != nil {
		zap.L().Error("Failed to upload to S3", zap.Error(err))
		return fmt.Errorf("failed to upload to S3: %w", err)
	}

	fileHash := hex.EncodeToString(hasher.Sum(nil))

	span.AddEvent("publishing to Kafka")
	zap.L().Info("Publishing IngestEvent to Kafka", zap.String("s3_uri", s3URI), zap.String("hash", fileHash))
	event := &prismv1.IngestEvent{
		EventId:        uuid.New().String(),
		TenantId:       tenantID,
		S3Uri:          s3URI,
		FileHashSha256: fileHash,
		Timestamp:      time.Now().Format(time.RFC3339),
		Metadata: map[string]string{
			"original_filename": filename,
		},
	}

	if err := f.kafka.PublishIngestEvent(ctx, event); err != nil {
		zap.L().Error("Failed to publish IngestEvent", zap.Error(err))
		return fmt.Errorf("failed to publish ingest event: %w", err)
	}

	statusPayload, err := json.Marshal(map[string]string{
		"document_id":   event.EventId,
		"tenant_id":     tenantID,
		"filename":      filename,
		"current_stage": "api-gateway",
		"status":        "PENDING",
		"error_message": "",
		"updated_at":    time.Now().Format(time.RFC3339),
		"s3_uri":        s3URI,
		"file_hash":     fileHash,
	})
	if err != nil {
		zap.L().Error("Failed to marshal status event", zap.Error(err))
		return fmt.Errorf("failed to marshal status event: %w", err)
	}
	_ = f.kafka.PublishStatusEvent(ctx, tenantID, statusPayload)

	return nil
}
