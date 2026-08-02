package pipeline

import (
	"context"
	"testing"
	"time"

	prismv1 "contracts/gen/go/proto/prism/v1"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/mock"
)

type MockDedupCache struct {
	mock.Mock
}

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

type dedupTestSuite struct {
	cache          *MockDedupCache
	exactHandler   *ExactHashHandler
	minHashHandler *MinHashLSHHandler
}

func setupDedupTest() (*dedupTestSuite, context.Context) {
	cache := new(MockDedupCache)
	return &dedupTestSuite{
		cache:          cache,
		exactHandler:   NewExactHashHandler(cache),
		minHashHandler: NewMinHashLSHHandler(cache),
	}, context.Background()
}

func TestExactHashHandler(t *testing.T) {
	suite, ctx := setupDedupTest()
	event := &prismv1.IngestEvent{FileHashSha256: "hash123", EventId: "evt1"}
	suite.cache.On("Exists", ctx, "doc:hash:hash123").Return(true, nil).Once()
	res, err := suite.exactHandler.Handle(ctx, event)
	assert.NoError(t, err)
	assert.Equal(t, ResultExactDuplicate, res)
	suite.cache.On("Exists", ctx, "doc:hash:hash123").Return(false, nil).Once()
	suite.cache.On("Set", ctx, "doc:hash:hash123", "evt1", time.Duration(0)).Return(nil).Once()
	res, err = suite.exactHandler.Handle(ctx, event)
	assert.NoError(t, err)
	assert.Equal(t, ResultNewDocument, res)

	suite.cache.AssertExpectations(t)
}

func TestMinHashLSHHandler(t *testing.T) {
	suite, ctx := setupDedupTest()
	event := &prismv1.IngestEvent{
		Metadata: map[string]string{"is_version_update": "true"},
	}
	res, err := suite.minHashHandler.Handle(ctx, event)
	assert.NoError(t, err)
	assert.Equal(t, ResultVersionUpdate, res)
	event.Metadata = nil
	res, err = suite.minHashHandler.Handle(ctx, event)
	assert.NoError(t, err)
	assert.Equal(t, ResultNewDocument, res)
}
