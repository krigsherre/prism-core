package redis

import (
	"context"
	"errors"
	"testing"
	"time"

	"triage-worker/internal/config"

	"github.com/redis/go-redis/v9"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/mock"
)

type MockRedisClient struct {
	mock.Mock
}

func (m *MockRedisClient) Exists(ctx context.Context, keys ...string) *redis.IntCmd {
	args := m.Called(ctx, keys)
	cmd := redis.NewIntCmd(ctx)
	if args.Error(1) != nil {
		cmd.SetErr(args.Error(1))
	} else {
		cmd.SetVal(args.Get(0).(int64))
	}
	return cmd
}

func (m *MockRedisClient) Set(ctx context.Context, key string, value interface{}, expiration time.Duration) *redis.StatusCmd {
	args := m.Called(ctx, key, value, expiration)
	cmd := redis.NewStatusCmd(ctx)
	if args.Error(0) != nil {
		cmd.SetErr(args.Error(0))
	} else {
		cmd.SetVal("OK")
	}
	return cmd
}

func (m *MockRedisClient) Incr(ctx context.Context, key string) *redis.IntCmd {
	args := m.Called(ctx, key)
	cmd := redis.NewIntCmd(ctx)
	if args.Error(1) != nil {
		cmd.SetErr(args.Error(1))
	} else {
		cmd.SetVal(args.Get(0).(int64))
	}
	return cmd
}

type redisTestSuite struct {
	client *MockRedisClient
	cache  *RedisCache
}

func setupRedisTest() (*redisTestSuite, context.Context) {
	mockClient := new(MockRedisClient)
	return &redisTestSuite{
		client: mockClient,
		cache:  &RedisCache{client: mockClient},
	}, context.Background()
}

func TestNewRedisCache(t *testing.T) {
	cfg := &config.Config{
		Redis: config.RedisConfig{
			Addr: "localhost:6379",
		},
	}
	cache := NewRedisCache(cfg)
	assert.NotNil(t, cache)
}

func TestRedisCache_Exists(t *testing.T) {
	suite, ctx := setupRedisTest()

	suite.client.On("Exists", ctx, []string{"key1"}).Return(int64(1), nil).Once()
	exists, err := suite.cache.Exists(ctx, "key1")
	assert.NoError(t, err)
	assert.True(t, exists)

	suite.client.On("Exists", ctx, []string{"key2"}).Return(int64(0), nil).Once()
	exists, err = suite.cache.Exists(ctx, "key2")
	assert.NoError(t, err)
	assert.False(t, exists)

	suite.client.On("Exists", ctx, []string{"key3"}).Return(int64(0), errors.New("redis down")).Times(3)
	exists, err = suite.cache.Exists(ctx, "key3")
	assert.Error(t, err)
	assert.False(t, exists)

	suite.client.AssertExpectations(t)
}

func TestRedisCache_Set(t *testing.T) {
	suite, ctx := setupRedisTest()
	suite.client.On("Set", ctx, "key1", "val1", time.Duration(0)).Return(nil).Once()
	err := suite.cache.Set(ctx, "key1", "val1", 0)
	assert.NoError(t, err)
	suite.client.On("Set", ctx, "key2", "val2", time.Duration(0)).Return(errors.New("redis down")).Times(3)
	err = suite.cache.Set(ctx, "key2", "val2", 0)
	assert.Error(t, err)
	suite.client.AssertExpectations(t)
}

func TestRedisCache_Incr(t *testing.T) {
	suite, ctx := setupRedisTest()
	suite.client.On("Incr", ctx, "key1").Return(int64(5), nil).Once()
	count, err := suite.cache.Incr(ctx, "key1")
	assert.NoError(t, err)
	assert.Equal(t, int64(5), count)
	suite.client.On("Incr", ctx, "key2").Return(int64(0), errors.New("redis down")).Times(3)
	count, err = suite.cache.Incr(ctx, "key2")
	assert.Error(t, err)
	assert.Equal(t, int64(0), count)
	suite.client.AssertExpectations(t)
}
