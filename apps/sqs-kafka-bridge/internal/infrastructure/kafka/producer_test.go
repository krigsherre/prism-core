package kafka

import (
	"context"
	"errors"
	"testing"

	"sqs-kafka-bridge/internal/config"

	"github.com/segmentio/kafka-go"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/mock"
)

type MockKafkaWriter struct {
	mock.Mock
}

func (m *MockKafkaWriter) WriteMessages(ctx context.Context, msgs ...kafka.Message) error {
	args := m.Called(ctx, msgs)
	return args.Error(0)
}

func (m *MockKafkaWriter) Close() error {
	args := m.Called()
	return args.Error(0)
}

func TestNewKafkaProducer(t *testing.T) {
	cfg := &config.Config{
		Kafka: config.KafkaConfig{
			Broker: "localhost:9092",
			Topic:  "s3_discovery_events",
		},
	}

	producer := NewKafkaProducer(cfg)
	assert.NotNil(t, producer)
}

func TestKafkaProducer_PublishMessage(t *testing.T) {
	mockWriter := new(MockKafkaWriter)
	producer := &KafkaProducer{
		writer: mockWriter,
	}

	ctx := context.Background()
	key := []byte("key1")
	val := []byte("val1")

	mockWriter.On("WriteMessages", ctx, mock.Anything).Return(nil).Once()
	err := producer.PublishMessage(ctx, key, val)
	assert.NoError(t, err)

	mockWriter.On("WriteMessages", ctx, mock.Anything).Return(errors.New("broker down")).Times(3)
	err = producer.PublishMessage(ctx, key, val)
	assert.Error(t, err)

	mockWriter.AssertExpectations(t)
}

func TestKafkaProducer_Close(t *testing.T) {
	mockWriter := new(MockKafkaWriter)
	producer := &KafkaProducer{
		writer: mockWriter,
	}

	mockWriter.On("Close").Return(nil).Once()
	err := producer.Close()
	assert.NoError(t, err)

	mockWriter.AssertExpectations(t)
}
