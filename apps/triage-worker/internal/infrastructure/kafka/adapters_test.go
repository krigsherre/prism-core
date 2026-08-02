package kafka

import (
	"context"
	"errors"
	"testing"

	"triage-worker/internal/config"

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

type MockKafkaReader struct {
	mock.Mock
}

func (m *MockKafkaReader) FetchMessage(ctx context.Context) (kafka.Message, error) {
	args := m.Called(ctx)
	return args.Get(0).(kafka.Message), args.Error(1)
}

func (m *MockKafkaReader) CommitMessages(ctx context.Context, msgs ...kafka.Message) error {
	args := m.Called(ctx, msgs)
	return args.Error(0)
}

func (m *MockKafkaReader) Close() error {
	return nil
}

type kafkaTestSuite struct {
	writer   *MockKafkaWriter
	reader   *MockKafkaReader
	producer *KafkaProducer
	consumer *KafkaConsumer
}

func setupKafkaTest() (*kafkaTestSuite, context.Context) {
	mockWriter := new(MockKafkaWriter)
	mockReader := new(MockKafkaReader)

	return &kafkaTestSuite{
		writer:   mockWriter,
		reader:   mockReader,
		producer: &KafkaProducer{writer: mockWriter},
		consumer: &KafkaConsumer{reader: mockReader},
	}, context.Background()
}

func TestNewKafkaProducer(t *testing.T) {
	cfg := &config.Config{
		Kafka: config.KafkaConfig{
			Broker: "localhost:9092",
		},
	}
	producer := NewKafkaProducer(cfg, "test_topic")
	assert.NotNil(t, producer)
}

func TestNewKafkaConsumer(t *testing.T) {
	cfg := &config.Config{
		Kafka: config.KafkaConfig{
			Broker:          "localhost:9092",
			CommitIntervals: "1s",
			IngestTopic:     "test_topic",
		},
	}
	consumer := NewKafkaConsumer(cfg)
	assert.NotNil(t, consumer)
}

func TestKafkaProducer_PublishMessage(t *testing.T) {
	suite, ctx := setupKafkaTest()
	suite.writer.On("WriteMessages", ctx, mock.Anything).Return(nil).Once()
	err := suite.producer.PublishMessage(ctx, []byte("k"), []byte("v"))
	assert.NoError(t, err)
	suite.writer.On("WriteMessages", ctx, mock.Anything).Return(errors.New("down")).Times(3)
	err = suite.producer.PublishMessage(ctx, []byte("k"), []byte("v"))
	assert.Error(t, err)
	suite.producer.Close()
	suite.writer.AssertExpectations(t)
}

func TestKafkaConsumer_FetchMessage(t *testing.T) {
	suite, ctx := setupKafkaTest()
	suite.reader.On("FetchMessage", ctx).Return(kafka.Message{Value: []byte("v")}, nil).Once()
	msg, err := suite.consumer.FetchMessage(ctx)
	assert.NoError(t, err)
	assert.Equal(t, []byte("v"), msg.Value)
	suite.reader.On("FetchMessage", ctx).Return(kafka.Message{}, errors.New("down")).Times(3)
	_, err = suite.consumer.FetchMessage(ctx)
	assert.Error(t, err)
	suite.consumer.Close()
	suite.reader.AssertExpectations(t)
}

func TestKafkaConsumer_CommitMessages(t *testing.T) {
	suite, ctx := setupKafkaTest()
	suite.reader.On("CommitMessages", ctx, mock.Anything).Return(nil).Once()
	err := suite.consumer.CommitMessages(ctx, kafka.Message{})
	assert.NoError(t, err)
	suite.reader.On("CommitMessages", ctx, mock.Anything).Return(errors.New("down")).Times(3)
	err = suite.consumer.CommitMessages(ctx, kafka.Message{})
	assert.Error(t, err)
	suite.reader.AssertExpectations(t)
}
