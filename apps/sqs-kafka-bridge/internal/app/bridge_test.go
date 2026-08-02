package app

import (
	"context"
	"errors"
	"testing"

	"sqs-kafka-bridge/internal/config"

	aws_sdk "github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/sqs/types"
	"github.com/stretchr/testify/mock"
	"go.uber.org/zap/zaptest"
)

type MockSQSClient struct {
	mock.Mock
}

func (m *MockSQSClient) ReceiveMessages(ctx context.Context, maxMessages int32) ([]types.Message, error) {
	args := m.Called(ctx, maxMessages)
	return args.Get(0).([]types.Message), args.Error(1)
}

func (m *MockSQSClient) DeleteMessage(ctx context.Context, receiptHandle string) error {
	args := m.Called(ctx, receiptHandle)
	return args.Error(0)
}

type MockKafkaProducer struct {
	mock.Mock
}

func (m *MockKafkaProducer) PublishMessage(ctx context.Context, key, value []byte) error {
	args := m.Called(ctx, key, value)
	return args.Error(0)
}

func (m *MockKafkaProducer) Close() error {
	args := m.Called()
	return args.Error(0)
}

func TestProcessBatch_Success(t *testing.T) {
	mockSQS := new(MockSQSClient)
	mockKafka := new(MockKafkaProducer)
	logger := zaptest.NewLogger(t)

	cfg := &config.AppConfig{MaxMessages: 10}
	worker := NewBridgeWorker(logger, mockSQS, mockKafka, cfg)
	ctx := context.Background()

	messages := []types.Message{
		{
			MessageId:     aws_sdk.String("msg-1"),
			Body:          aws_sdk.String(`{"event": "test"}`),
			ReceiptHandle: aws_sdk.String("receipt-1"),
		},
	}
	mockSQS.On("ReceiveMessages", ctx, int32(10)).Return(messages, nil)

	mockKafka.On("PublishMessage", mock.Anything, []byte("msg-1"), []byte(`{"event": "test"}`)).Return(nil)

	mockSQS.On("DeleteMessage", mock.Anything, mock.Anything).Return(nil)

	worker.processBatch(ctx)

	mockSQS.AssertExpectations(t)
	mockKafka.AssertExpectations(t)
}

func TestProcessBatch_KafkaFails_SQSNotDeleted(t *testing.T) {
	mockSQS := new(MockSQSClient)
	mockKafka := new(MockKafkaProducer)
	logger := zaptest.NewLogger(t)

	cfg := &config.AppConfig{MaxMessages: 10}
	worker := NewBridgeWorker(logger, mockSQS, mockKafka, cfg)
	ctx := context.Background()

	messages := []types.Message{
		{
			MessageId:     aws_sdk.String("msg-1"),
			Body:          aws_sdk.String(`{"event": "test"}`),
			ReceiptHandle: aws_sdk.String("receipt-1"),
		},
	}
	mockSQS.On("ReceiveMessages", mock.Anything, int32(10)).Return(messages, nil)
	mockKafka.On("PublishMessage", mock.Anything, []byte("msg-1"), []byte(`{"event": "test"}`)).Return(errors.New("kafka is down"))
	worker.processBatch(ctx)

	mockSQS.AssertExpectations(t)
	mockKafka.AssertExpectations(t)
}

func TestBridgeWorker_Start(t *testing.T) {
	mockSQS := new(MockSQSClient)
	mockKafka := new(MockKafkaProducer)
	logger := zaptest.NewLogger(t)

	cfg := &config.AppConfig{MaxMessages: 10}
	worker := NewBridgeWorker(logger, mockSQS, mockKafka, cfg)

	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	worker.Start(ctx)
}
