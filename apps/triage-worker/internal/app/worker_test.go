package app

import (
	"context"
	"errors"
	"testing"
	"time"

	prismv1 "contracts/gen/go/proto/prism/v1"
	"triage-worker/internal/config"

	"github.com/segmentio/kafka-go"
	"github.com/stretchr/testify/mock"
	"go.uber.org/zap"
	"google.golang.org/protobuf/proto"
)

type MockConsumer struct{ mock.Mock }

func (m *MockConsumer) FetchMessage(ctx context.Context) (kafka.Message, error) {
	args := m.Called(ctx)
	return args.Get(0).(kafka.Message), args.Error(1)
}
func (m *MockConsumer) CommitMessages(ctx context.Context, msgs ...kafka.Message) error {
	args := m.Called(ctx, msgs)
	return args.Error(0)
}
func (m *MockConsumer) Close() error { return nil }

type MockProducer struct{ mock.Mock }

func (m *MockProducer) PublishMessage(ctx context.Context, key, value []byte) error {
	args := m.Called(ctx, key, value)
	return args.Error(0)
}
func (m *MockProducer) Close() error { return nil }

type MockDedupCache struct{ mock.Mock }

func (m *MockDedupCache) Exists(ctx context.Context, key string) (bool, error) {
	args := m.Called(ctx, key)
	return args.Bool(0), args.Error(1)
}
func (m *MockDedupCache) Set(ctx context.Context, key string, value string, expiration time.Duration) error {
	args := m.Called(ctx, key, value, expiration)
	return args.Error(0)
}
func (m *MockDedupCache) Incr(ctx context.Context, key string) (int64, error) {
	args := m.Called(ctx, key)
	return args.Get(0).(int64), args.Error(1)
}

type workerTestSuite struct {
	consumer *MockConsumer
	dlq      *MockProducer
	gpu      *MockProducer
	status   *MockProducer
	cache    *MockDedupCache
	worker   *TriageWorker
}

func setupWorkerTest() *workerTestSuite {
	suite := &workerTestSuite{
		consumer: new(MockConsumer),
		dlq:      new(MockProducer),
		gpu:      new(MockProducer),
		status:   new(MockProducer),
		cache:    new(MockDedupCache),
	}
	cfg := &config.AppConfig{Concurrency: 10, MaxRetries: 3}
	logger := zap.NewNop()

	suite.worker = NewTriageWorker(
		logger, suite.consumer, suite.dlq, suite.gpu, suite.status, nil, suite.cache, cfg,
	)

	suite.status.On("PublishMessage", mock.Anything, mock.Anything, mock.Anything).Return(nil)
	return suite
}

func TestTriageWorker_Start(t *testing.T) {
	suite := setupWorkerTest()
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	suite.worker.Start(ctx)
}

func TestTriageWorker_processMessage_Success(t *testing.T) {
	suite := setupWorkerTest()
	ctx := context.Background()
	event := &prismv1.IngestEvent{TenantId: "t1", EventId: "e1", FileHashSha256: "hash1"}
	val, _ := proto.Marshal(event)

	suite.cache.On("Exists", mock.Anything, "doc:hash:hash1").Return(false, nil).Once()
	suite.cache.On("Set", mock.Anything, "doc:hash:hash1", "e1", time.Duration(0)).Return(nil).Once()
	suite.gpu.On("PublishMessage", mock.Anything, []byte("t1"), val).Return(nil).Once()
	suite.consumer.On("CommitMessages", mock.Anything, mock.Anything).Return(nil).Once()

	suite.worker.processMessage(ctx, kafka.Message{Value: val, Key: []byte("key"), Offset: 0})

	suite.cache.AssertExpectations(t)
	suite.gpu.AssertExpectations(t)
	suite.consumer.AssertExpectations(t)
}

func TestTriageWorker_processMessage_UnmarshalFail(t *testing.T) {
	suite := setupWorkerTest()
	ctx := context.Background()

	suite.cache.On("Incr", mock.Anything, "dlq:failcount:unknown").Return(int64(1), nil).Once()

	suite.worker.processMessage(ctx, kafka.Message{Value: []byte("invalid"), Key: []byte("key"), Offset: 0})

	suite.cache.AssertExpectations(t)
}

func TestTriageWorker_processMessage_DedupFail(t *testing.T) {
	suite := setupWorkerTest()
	ctx := context.Background()
	event := &prismv1.IngestEvent{TenantId: "t1", EventId: "e1", FileHashSha256: "hash1"}
	val, _ := proto.Marshal(event)

	suite.cache.On("Exists", mock.Anything, "doc:hash:hash1").Return(false, errors.New("err")).Once()
	suite.cache.On("Incr", mock.Anything, "dlq:failcount:e1").Return(int64(1), nil).Once()

	suite.worker.processMessage(ctx, kafka.Message{Value: val, Key: []byte("key"), Offset: 0})

	suite.cache.AssertExpectations(t)
}

func TestTriageWorker_processMessage_RoutingFail(t *testing.T) {
	suite := setupWorkerTest()
	ctx := context.Background()
	event := &prismv1.IngestEvent{TenantId: "t1", EventId: "e1", FileHashSha256: "hash1"}
	val, _ := proto.Marshal(event)

	suite.cache.On("Exists", mock.Anything, "doc:hash:hash1").Return(false, nil).Once()
	suite.cache.On("Set", mock.Anything, "doc:hash:hash1", "e1", time.Duration(0)).Return(nil).Once()
	suite.gpu.On("PublishMessage", mock.Anything, []byte("t1"), val).Return(errors.New("err")).Once()
	suite.cache.On("Incr", mock.Anything, "dlq:failcount:e1").Return(int64(1), nil).Once()

	suite.worker.processMessage(ctx, kafka.Message{Value: val, Key: []byte("key"), Offset: 0})

	suite.cache.AssertExpectations(t)
	suite.gpu.AssertExpectations(t)
}

func TestTriageWorker_processMessage_ExactDuplicate(t *testing.T) {
	suite := setupWorkerTest()
	ctx := context.Background()
	event := &prismv1.IngestEvent{TenantId: "t1", EventId: "e1", FileHashSha256: "hash1"}
	val, _ := proto.Marshal(event)

	suite.cache.On("Exists", mock.Anything, "doc:hash:hash1").Return(true, nil).Once()
	suite.consumer.On("CommitMessages", mock.Anything, mock.Anything).Return(nil).Once()

	suite.worker.processMessage(ctx, kafka.Message{Value: val, Key: []byte("key"), Offset: 0})

	suite.cache.AssertExpectations(t)
	suite.consumer.AssertExpectations(t)
}

func TestTriageWorker_processMessage_VersionUpdate(t *testing.T) {
	suite := setupWorkerTest()
	ctx := context.Background()
	event := &prismv1.IngestEvent{
		TenantId:       "t1",
		EventId:        "e1",
		FileHashSha256: "hash1",
		Metadata:       map[string]string{"is_version_update": "true"},
	}
	val, _ := proto.Marshal(event)

	suite.cache.On("Exists", mock.Anything, "doc:hash:hash1").Return(false, nil).Once()
	suite.cache.On("Set", mock.Anything, "doc:hash:hash1", "e1", time.Duration(0)).Return(nil).Once()
	suite.gpu.On("PublishMessage", mock.Anything, []byte("t1"), val).Return(nil).Once()
	suite.consumer.On("CommitMessages", mock.Anything, mock.Anything).Return(nil).Once()

	suite.worker.processMessage(ctx, kafka.Message{Value: val, Key: []byte("key"), Offset: 0})

	suite.cache.AssertExpectations(t)
	suite.gpu.AssertExpectations(t)
	suite.consumer.AssertExpectations(t)
}

func TestTriageWorker_handleFailure_Retry(t *testing.T) {
	suite := setupWorkerTest()
	ctx := context.Background()
	event := &prismv1.IngestEvent{TenantId: "t1", EventId: "e1", FileHashSha256: "hash1"}

	suite.cache.On("Incr", mock.Anything, "dlq:failcount:e1").Return(int64(1), nil).Once()

	suite.worker.handleFailure(ctx, kafka.Message{Value: []byte("val"), Key: []byte("key")}, event, "err")

	suite.cache.AssertExpectations(t)
}

func TestTriageWorker_handleFailure_MaxRetriesReachedDLQ(t *testing.T) {
	suite := setupWorkerTest()
	ctx := context.Background()
	event := &prismv1.IngestEvent{TenantId: "t1", EventId: "e1", FileHashSha256: "hash1"}

	suite.cache.On("Incr", mock.Anything, "dlq:failcount:e1").Return(int64(3), nil).Once()
	suite.dlq.On("PublishMessage", mock.Anything, []byte("key"), []byte("val")).Return(nil).Once()
	suite.consumer.On("CommitMessages", mock.Anything, mock.Anything).Return(nil).Once()

	suite.worker.handleFailure(ctx, kafka.Message{Value: []byte("val"), Key: []byte("key")}, event, "err")

	suite.cache.AssertExpectations(t)
	suite.dlq.AssertExpectations(t)
	suite.consumer.AssertExpectations(t)
}
