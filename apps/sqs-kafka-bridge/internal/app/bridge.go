package app

import (
	"context"
	"sync"
	"time"

	"github.com/aws/aws-sdk-go-v2/service/sqs/types"
	"go.opentelemetry.io/otel"
	"go.uber.org/zap"

	"sqs-kafka-bridge/internal/config"
	"sqs-kafka-bridge/internal/infrastructure/aws"
	"sqs-kafka-bridge/internal/infrastructure/kafka"
)

type BridgeWorker struct {
	logger   *zap.Logger
	sqs      aws.SQSClient
	producer kafka.Producer
	cfg      *config.AppConfig
}

func NewBridgeWorker(logger *zap.Logger, sqsClient aws.SQSClient, producer kafka.Producer, cfg *config.AppConfig) *BridgeWorker {
	return &BridgeWorker{
		logger:   logger,
		sqs:      sqsClient,
		producer: producer,
		cfg:      cfg,
	}
}

func (w *BridgeWorker) Start(ctx context.Context) {
	w.logger.Info("Starting SQS to Kafka Bridge worker loop")

	for {
		select {
		case <-ctx.Done():
			w.logger.Info("Context cancelled, shutting down bridge worker loop gracefully...")
			return
		default:
			w.processBatch(ctx)
		}
	}
}

func (w *BridgeWorker) processBatch(ctx context.Context) {
	messages, err := w.sqs.ReceiveMessages(ctx, w.cfg.MaxMessages)
	if err != nil {
		w.logger.Error("Failed to receive messages from SQS", zap.Error(err))
		time.Sleep(2 * time.Second)
		return
	}

	var wg sync.WaitGroup
	for _, msg := range messages {
		wg.Add(1)
		go func(m types.Message) {
			defer wg.Done()

			tracer := otel.Tracer("sqs-kafka-bridge")
			ctx, span := tracer.Start(ctx, "processMessage")
			defer span.End()

			if ctx.Err() != nil {
				w.logger.Info("Batch processing interrupted by shutdown signal")
				return
			}

			w.logger.Info("Processing SQS Message", zap.String("messageId", *m.MessageId))

			err := w.producer.PublishMessage(ctx, []byte(*m.MessageId), []byte(*m.Body))
			if err != nil {
				w.logger.Error("Failed to publish message to Kafka, retaining in SQS", zap.Error(err))
				return
			}

			err = w.sqs.DeleteMessage(ctx, *m.ReceiptHandle)
			if err != nil {
				w.logger.Error("Failed to delete message from SQS", zap.Error(err), zap.String("receiptHandle", *m.ReceiptHandle))
			} else {
				w.logger.Debug("Successfully forwarded event to Kafka and deleted from SQS", zap.String("messageId", *m.MessageId))
			}
		}(msg)
	}

	wg.Wait()
}
