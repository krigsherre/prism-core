package kafka

import (
	"context"
	"time"

	"github.com/avast/retry-go/v4"
	"github.com/segmentio/kafka-go"
	"triage-worker/internal/config"
)

type Consumer interface {
	FetchMessage(ctx context.Context) (kafka.Message, error)
	CommitMessages(ctx context.Context, msgs ...kafka.Message) error
	Close() error
}

type KafkaReader interface {
	FetchMessage(ctx context.Context) (kafka.Message, error)
	CommitMessages(ctx context.Context, msgs ...kafka.Message) error
	Close() error
}

type KafkaConsumer struct {
	reader KafkaReader
}

func NewKafkaConsumer(cfg *config.Config) *KafkaConsumer {
	interval, _ := time.ParseDuration(cfg.Kafka.CommitIntervals)
	if interval == 0 {
		interval = time.Second
	}

	reader := kafka.NewReader(kafka.ReaderConfig{
		Brokers:        []string{cfg.Kafka.Broker},
		GroupID:        cfg.Kafka.ConsumerGroup,
		Topic:          cfg.Kafka.IngestTopic,
		MinBytes:       cfg.Kafka.MinBytes,
		MaxBytes:       cfg.Kafka.MaxBytes,
		CommitInterval: interval,
	})
	return &KafkaConsumer{reader: reader}
}

func (k *KafkaConsumer) FetchMessage(ctx context.Context) (kafka.Message, error) {
	var msg kafka.Message
	err := retry.Do(
		func() error {
			m, err := k.reader.FetchMessage(ctx)
			if err != nil {
				return err
			}
			msg = m
			return nil
		},
		retry.Context(ctx),
		retry.Attempts(3),
		retry.DelayType(retry.BackOffDelay),
		retry.LastErrorOnly(true),
	)
	return msg, err
}

func (k *KafkaConsumer) CommitMessages(ctx context.Context, msgs ...kafka.Message) error {
	return retry.Do(
		func() error {
			return k.reader.CommitMessages(ctx, msgs...)
		},
		retry.Context(ctx),
		retry.Attempts(3),
		retry.DelayType(retry.BackOffDelay),
		retry.LastErrorOnly(true),
	)
}

func (k *KafkaConsumer) Close() error {
	return k.reader.Close()
}
