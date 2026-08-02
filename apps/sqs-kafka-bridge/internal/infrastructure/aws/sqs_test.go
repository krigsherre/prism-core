package aws

import (
	"context"
	"errors"
	"testing"

	"sqs-kafka-bridge/internal/config"

	"github.com/aws/aws-sdk-go-v2/service/sqs"
	"github.com/aws/aws-sdk-go-v2/service/sqs/types"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/mock"
)

type MockSQSAPI struct {
	mock.Mock
}

func (m *MockSQSAPI) ReceiveMessage(ctx context.Context, params *sqs.ReceiveMessageInput, optFns ...func(*sqs.Options)) (*sqs.ReceiveMessageOutput, error) {
	args := m.Called(ctx, params)
	if args.Get(0) == nil {
		return nil, args.Error(1)
	}
	return args.Get(0).(*sqs.ReceiveMessageOutput), args.Error(1)
}

func (m *MockSQSAPI) DeleteMessage(ctx context.Context, params *sqs.DeleteMessageInput, optFns ...func(*sqs.Options)) (*sqs.DeleteMessageOutput, error) {
	args := m.Called(ctx, params)
	if args.Get(0) == nil {
		return nil, args.Error(1)
	}
	return args.Get(0).(*sqs.DeleteMessageOutput), args.Error(1)
}

func TestNewSQSAdapter(t *testing.T) {
	cfg := &config.Config{
		AWS: config.AWSConfig{
			Region:          "us-east-1",
			SQSQueueURL:     "http://localhost:9324/queue/test",
			SQSEndpoint:     "http://localhost:9324",
			WaitTimeSeconds: 20,
		},
	}

	ctx := context.Background()
	adapter, err := NewSQSAdapter(ctx, cfg)

	assert.NoError(t, err)
	assert.NotNil(t, adapter)
	assert.Equal(t, "http://localhost:9324/queue/test", adapter.queueURL)
	assert.Equal(t, int32(20), adapter.waitTimeSeconds)
}

func TestSQSAdapter_ReceiveMessages(t *testing.T) {
	mockAPI := new(MockSQSAPI)
	adapter := &SQSAdapter{
		client:          mockAPI,
		queueURL:        "http://test-queue",
		waitTimeSeconds: 20,
	}

	ctx := context.Background()

	mockAPI.On("ReceiveMessage", ctx, mock.Anything).Return(&sqs.ReceiveMessageOutput{
		Messages: []types.Message{{}},
	}, nil).Once()

	msgs, err := adapter.ReceiveMessages(ctx, 10)
	assert.NoError(t, err)
	assert.Len(t, msgs, 1)

	mockAPI.On("ReceiveMessage", ctx, mock.Anything).Return(nil, errors.New("network error")).Times(3) // 3 retries
	msgs, err = adapter.ReceiveMessages(ctx, 10)
	assert.Error(t, err)
	assert.Nil(t, msgs)

	mockAPI.AssertExpectations(t)
}

func TestSQSAdapter_DeleteMessage(t *testing.T) {
	mockAPI := new(MockSQSAPI)
	adapter := &SQSAdapter{
		client:          mockAPI,
		queueURL:        "http://test-queue",
		waitTimeSeconds: 20,
	}

	ctx := context.Background()

	mockAPI.On("DeleteMessage", ctx, mock.Anything).Return(&sqs.DeleteMessageOutput{}, nil).Once()

	err := adapter.DeleteMessage(ctx, "receipt-handle")
	assert.NoError(t, err)

	mockAPI.On("DeleteMessage", ctx, mock.Anything).Return(nil, errors.New("delete error")).Times(3)
	err = adapter.DeleteMessage(ctx, "receipt-handle")
	assert.Error(t, err)

	mockAPI.AssertExpectations(t)
}
