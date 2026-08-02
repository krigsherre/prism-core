package app

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"testing"
	"time"

	"s3-connector/internal/config"
	"s3-connector/internal/domain"

	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/segmentio/kafka-go"
)

type mockKafka struct {
	messages []kafka.Message
	commits  int
}

func (m *mockKafka) FetchMessage(ctx context.Context) (kafka.Message, error) {
	if len(m.messages) == 0 {
		return kafka.Message{}, fmt.Errorf("timeout")
	}
	msg := m.messages[0]
	m.messages = m.messages[1:]
	return msg, nil
}

func (m *mockKafka) CommitMessages(ctx context.Context, msgs ...kafka.Message) error {
	m.commits += len(msgs)
	return nil
}

type mockS3 struct {
	content []byte
}

func (m *mockS3) GetObject(ctx context.Context, bucket, key string) (*s3.GetObjectOutput, error) {
	return &s3.GetObjectOutput{
		Body: io.NopCloser(bytes.NewReader(m.content)),
	}, nil
}

type mockCache struct {
	filterNewResponse []string
}

func (m *mockCache) FilterNew(ctx context.Context, etags []string) ([]string, error) {
	return m.filterNewResponse, nil
}

func (m *mockCache) CacheEtags(ctx context.Context, etags []string) error {
	return nil
}

type mockDB struct {
	findExistingResponse []string
}

func (m *mockDB) FindExisting(ctx context.Context, etags []string) ([]string, error) {
	return m.findExistingResponse, nil
}

func (m *mockDB) BulkMarkProcessed(ctx context.Context, etags []string) error {
	return nil
}

type mockGateway struct {
	posted int
}

func (m *mockGateway) PostFile(ctx context.Context, tenantID, filename string, stream io.Reader) error {
	m.posted++
	return nil
}

func TestIngestor_ProcessBatch(t *testing.T) {
	event := domain.S3DiscoveryEvent{
		TenantID: "tenant1",
		Bucket:   "bucket1",
		Key:      "key1",
		ETag:     "etag1",
	}
	eventBytes, _ := json.Marshal(event)

	k := &mockKafka{
		messages: []kafka.Message{{Value: eventBytes}},
	}
	s := &mockS3{content: []byte("file content")}
	c := &mockCache{filterNewResponse: []string{"etag1"}}
	db := &mockDB{findExistingResponse: []string{}}
	gw := &mockGateway{}
	cfg := &config.AppConfig{
		MaxBatchSize: 500,
		FetchTimeout: 1 * time.Second,
	}

	ingestor := NewIngestor(k, s, c, db, gw, cfg)

	ctx := context.Background()

	err := ingestor.ProcessBatch(ctx, k.messages)
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}

	if gw.posted != 1 {
		t.Errorf("expected 1 file posted, got %d", gw.posted)
	}
}

func TestIngestor_ProcessBatch_Duplicate(t *testing.T) {
	event := domain.S3DiscoveryEvent{
		TenantID: "tenant1",
		Bucket:   "bucket1",
		Key:      "key1",
		ETag:     "etag1",
	}
	eventBytes, _ := json.Marshal(event)

	k := &mockKafka{
		messages: []kafka.Message{{Value: eventBytes}},
	}
	s := &mockS3{content: []byte("file content")}
	c := &mockCache{filterNewResponse: []string{}}
	db := &mockDB{findExistingResponse: []string{}}
	gw := &mockGateway{}
	cfg := &config.AppConfig{
		MaxBatchSize: 500,
		FetchTimeout: 1 * time.Second,
	}

	ingestor := NewIngestor(k, s, c, db, gw, cfg)

	ctx := context.Background()
	err := ingestor.ProcessBatch(ctx, k.messages)
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}

	if gw.posted != 0 {
		t.Errorf("expected 0 files posted due to cache hit, got %d", gw.posted)
	}
}

func TestIngestor_Start(t *testing.T) {
	k := &mockKafka{
		messages: []kafka.Message{},
	}
	s := &mockS3{content: []byte("file content")}
	c := &mockCache{filterNewResponse: []string{}}
	db := &mockDB{findExistingResponse: []string{}}
	gw := &mockGateway{}
	cfg := &config.AppConfig{
		MaxBatchSize: 500,
		FetchTimeout: 10 * time.Millisecond,
	}

	ingestor := NewIngestor(k, s, c, db, gw, cfg)

	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Millisecond)
	defer cancel()

	ingestor.Start(ctx)
}
