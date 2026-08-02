package s3

import (
	"context"
	"strings"
	"testing"

	"api-gateway/internal/config"

	"github.com/stretchr/testify/assert"
)

func TestNewS3Client(t *testing.T) {
	cfg := &config.Config{
		S3: config.S3Config{
			Region:   "us-east-1",
			Endpoint: "http://localhost:4566",
			Bucket:   "test-bucket",
		},
	}
	client, err := NewS3Client(context.Background(), cfg)
	assert.NoError(t, err)
	assert.NotNil(t, client)
}

func TestS3Client_UploadStream_Failure(t *testing.T) {
	cfg := &config.Config{
		S3: config.S3Config{
			Region:   "us-east-1",
			Endpoint: "http://0.0.0.0:1",
			Bucket:   "test-bucket",
		},
	}
	client, err := NewS3Client(context.Background(), cfg)
	assert.NoError(t, err)
	ctx := context.Background()
	_, err = client.UploadStream(ctx, "key", strings.NewReader("content"))
	assert.Error(t, err)
}
