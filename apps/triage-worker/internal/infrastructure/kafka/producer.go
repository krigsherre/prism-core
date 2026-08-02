package kafka

import (
	"context"

	"github.com/avast/retry-go/v4"
	"github.com/segmentio/kafka-go"
	"triage-worker/internal/config"
)

type Producer interface {
	PublishMessage(ctx context.Context, key, value []byte) error
	Close() error
}

type KafkaWriter interface {
	WriteMessages(ctx context.Context, msgs ...kafka.Message) error
	Close() error
}

type KafkaProducer struct {
	writer KafkaWriter
}

func NewKafkaProducer(cfg *config.Config, topic string) *KafkaProducer {
	writer := &kafka.Writer{
		Addr:                   kafka.TCP(cfg.Kafka.Broker),
		Topic:                  topic,
		Balancer:               &kafka.LeastBytes{},
		AllowAutoTopicCreation: true,
	}
	return &KafkaProducer{writer: writer}
}

func (k *KafkaProducer) PublishMessage(ctx context.Context, key, value []byte) error {
	return retry.Do(
		func() error {
			return k.writer.WriteMessages(ctx, kafka.Message{
				Key:   key,
				Value: value,
			})
		},
		retry.Context(ctx),
		retry.Attempts(3),
		retry.DelayType(retry.BackOffDelay),
		retry.LastErrorOnly(true),
	)
}

func (k *KafkaProducer) Close() error {
	return k.writer.Close()
}
