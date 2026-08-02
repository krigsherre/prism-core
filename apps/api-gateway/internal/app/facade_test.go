package app

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"strings"
	"testing"

	prismv1 "contracts/gen/go/proto/prism/v1"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/mock"
)

type MockS3Uploader struct {
	mock.Mock
}

func (m *MockS3Uploader) UploadStream(ctx context.Context, key string, body io.Reader) (string, error) {
	args := m.Called(ctx, key, body)
	return args.String(0), args.Error(1)
}

type MockKafkaPublisher struct {
	mock.Mock
}

func (m *MockKafkaPublisher) PublishIngestEvent(ctx context.Context, event *prismv1.IngestEvent) error {
	args := m.Called(ctx, event)
	return args.Error(0)
}

func (m *MockKafkaPublisher) PublishStatusEvent(ctx context.Context, tenantID string, payload []byte) error {
	args := m.Called(ctx, tenantID, payload)
	return args.Error(0)
}

func (m *MockKafkaPublisher) Close() error {
	return nil
}

func TestProcessUpload_Success(t *testing.T) {
	mockS3 := new(MockS3Uploader)
	mockKafka := new(MockKafkaPublisher)

	facade := NewIngressFacade(mockS3, mockKafka)

	mockS3.On("UploadStream", mock.Anything, mock.Anything, mock.Anything).Return("s3://bucket/key", nil).Once()
	mockKafka.On("PublishIngestEvent", mock.Anything, mock.Anything).Return(nil).Once()
	mockKafka.On("PublishStatusEvent", mock.Anything, "tenant1", mock.Anything).Return(nil).Once()

	err := facade.ProcessUpload(context.Background(), "tenant1", "file.pdf", strings.NewReader("content"))

	assert.NoError(t, err)
	mockS3.AssertExpectations(t)
	mockKafka.AssertExpectations(t)
}

func TestProcessUpload_StatusEventEscapesFilename(t *testing.T) {
	mockS3 := new(MockS3Uploader)
	mockKafka := new(MockKafkaPublisher)
	facade := NewIngressFacade(mockS3, mockKafka)

	mockS3.On("UploadStream", mock.Anything, mock.Anything, mock.Anything).Return("s3://bucket/key", nil).Once()
	mockKafka.On("PublishIngestEvent", mock.Anything, mock.Anything).Return(nil).Once()
	mockKafka.On("PublishStatusEvent", mock.Anything, "tenant1", mock.MatchedBy(func(payload []byte) bool {
		var body map[string]string
		if err := json.Unmarshal(payload, &body); err != nil {
			return false
		}
		return body["filename"] == `invoice "Q1".pdf` && body["status"] == "PENDING"
	})).Return(nil).Once()

	err := facade.ProcessUpload(context.Background(), "tenant1", `invoice "Q1".pdf`, strings.NewReader("content"))

	assert.NoError(t, err)
	mockKafka.AssertExpectations(t)
}

func TestProcessUpload_S3Failure(t *testing.T) {
	mockS3 := new(MockS3Uploader)
	mockKafka := new(MockKafkaPublisher)

	facade := NewIngressFacade(mockS3, mockKafka)

	mockS3.On("UploadStream", mock.Anything, mock.Anything, mock.Anything).Return("", errors.New("s3 error")).Once()

	err := facade.ProcessUpload(context.Background(), "tenant1", "file.pdf", strings.NewReader("content"))

	assert.Error(t, err)
	assert.Contains(t, err.Error(), "s3 error")
	mockS3.AssertExpectations(t)
	mockKafka.AssertExpectations(t)
}

func TestProcessUpload_KafkaFailure(t *testing.T) {
	mockS3 := new(MockS3Uploader)
	mockKafka := new(MockKafkaPublisher)

	facade := NewIngressFacade(mockS3, mockKafka)

	mockS3.On("UploadStream", mock.Anything, mock.Anything, mock.Anything).Return("s3://bucket/key", nil).Once()
	mockKafka.On("PublishIngestEvent", mock.Anything, mock.Anything).Return(errors.New("kafka error")).Once()

	err := facade.ProcessUpload(context.Background(), "tenant1", "file.pdf", strings.NewReader("content"))

	assert.Error(t, err)
	assert.Contains(t, err.Error(), "kafka error")
	mockS3.AssertExpectations(t)
	mockKafka.AssertExpectations(t)
}
