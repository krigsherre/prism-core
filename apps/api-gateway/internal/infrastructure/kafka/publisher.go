package kafka

import (
	"context"
	"time"

	"api-gateway/internal/config"
	prismv1 "contracts/gen/go/proto/prism/v1"
	"github.com/avast/retry-go/v4"
	"github.com/segmentio/kafka-go"
	"google.golang.org/protobuf/proto"
)

type Publisher interface {
	PublishIngestEvent(ctx context.Context, event *prismv1.IngestEvent) error
	PublishStatusEvent(ctx context.Context, tenantID string, payload []byte) error
	Close() error
}

type Writer interface {
	WriteMessages(ctx context.Context, msgs ...kafka.Message) error
	Close() error
}

type kafkaClient struct {
	writer       Writer
	statusWriter Writer
}

func NewKafkaPublisher(cfg *config.Config) Publisher {
	writer := &kafka.Writer{
		Addr:                   kafka.TCP(cfg.Kafka.Broker),
		Topic:                  cfg.Kafka.Topic,
		Balancer:               &kafka.LeastBytes{},
		BatchTimeout:           10 * time.Millisecond,
		AllowAutoTopicCreation: true,
	}
	statusWriter := &kafka.Writer{
		Addr:                   kafka.TCP(cfg.Kafka.Broker),
		Topic:                  "document_status_events",
		Balancer:               &kafka.LeastBytes{},
		BatchTimeout:           10 * time.Millisecond,
		AllowAutoTopicCreation: true,
	}
	return &kafkaClient{writer: writer, statusWriter: statusWriter}
}

func (k *kafkaClient) PublishIngestEvent(ctx context.Context, event *prismv1.IngestEvent) error {
	data, err := proto.Marshal(event)
	if err != nil {
		return err
	}

	msg := kafka.Message{
		Key:   []byte(event.TenantId),
		Value: data,
		Time:  time.Now(),
	}

	return retry.Do(
		func() error {
			return k.writer.WriteMessages(ctx, msg)
		},
		retry.Context(ctx),
		retry.Attempts(5),
		retry.Delay(200*time.Millisecond),
		retry.LastErrorOnly(true),
	)
}

func (k *kafkaClient) PublishStatusEvent(ctx context.Context, tenantID string, payload []byte) error {
	msg := kafka.Message{
		Key:   []byte(tenantID),
		Value: payload,
		Time:  time.Now(),
	}

	return retry.Do(
		func() error {
			return k.statusWriter.WriteMessages(ctx, msg)
		},
		retry.Context(ctx),
		retry.Attempts(5),
		retry.Delay(200*time.Millisecond),
		retry.LastErrorOnly(true),
	)
}

func (k *kafkaClient) Close() error {
	_ = k.statusWriter.Close()
	return k.writer.Close()
}
