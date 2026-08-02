package kafka

import (
	"context"
	"errors"
	"testing"

	"api-gateway/internal/config"
	prismv1 "contracts/gen/go/proto/prism/v1"

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
	return nil
}

func TestNewKafkaPublisher(t *testing.T) {
	cfg := &config.Config{
		Kafka: config.KafkaConfig{
			Broker: "localhost:9092",
			Topic:  "test_topic",
		},
	}

	publisher := NewKafkaPublisher(cfg)
	assert.NotNil(t, publisher)
}

func TestKafkaPublisher_PublishIngestEvent(t *testing.T) {
	mockWriter := new(MockKafkaWriter)
	mockStatusWriter := new(MockKafkaWriter)
	publisher := &kafkaClient{writer: mockWriter, statusWriter: mockStatusWriter}
	ctx := context.Background()

	event := &prismv1.IngestEvent{
		TenantId: "t1",
		EventId:  "e1",
	}

	mockWriter.On("WriteMessages", ctx, mock.Anything).Return(nil).Once()
	err := publisher.PublishIngestEvent(ctx, event)
	assert.NoError(t, err)

	mockWriter.On("WriteMessages", ctx, mock.Anything).Return(errors.New("down")).Times(5)
	err = publisher.PublishIngestEvent(ctx, event)
	assert.Error(t, err)

	publisher.Close()
	mockWriter.AssertExpectations(t)
}
