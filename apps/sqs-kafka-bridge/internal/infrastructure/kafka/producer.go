package kafka

import (
	"context"

	cfg "sqs-kafka-bridge/internal/config"

	"github.com/avast/retry-go/v4"
	"github.com/segmentio/kafka-go"
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

func NewKafkaProducer(config *cfg.Config) *KafkaProducer {
	writer := &kafka.Writer{
		Addr:     kafka.TCP(config.Kafka.Broker),
		Topic:    config.Kafka.Topic,
		Balancer: &kafka.LeastBytes{},
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
