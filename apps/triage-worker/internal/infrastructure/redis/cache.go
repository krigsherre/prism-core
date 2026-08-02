package redis

import (
	"context"
	"time"

	"github.com/avast/retry-go/v4"
	"github.com/redis/go-redis/v9"
	"triage-worker/internal/config"
)

type DedupCache interface {
	Exists(ctx context.Context, key string) (bool, error)
	Set(ctx context.Context, key string, value string, expiration time.Duration) error
	Incr(ctx context.Context, key string) (int64, error)
}

type RedisClient interface {
	Exists(ctx context.Context, keys ...string) *redis.IntCmd
	Set(ctx context.Context, key string, value interface{}, expiration time.Duration) *redis.StatusCmd
	Incr(ctx context.Context, key string) *redis.IntCmd
}

type RedisCache struct {
	client RedisClient
}

func NewRedisCache(cfg *config.Config) *RedisCache {
	client := redis.NewClient(&redis.Options{
		Addr: cfg.Redis.Addr,
	})
	return &RedisCache{client: client}
}

func (r *RedisCache) Exists(ctx context.Context, key string) (bool, error) {
	var exists bool
	err := retry.Do(
		func() error {
			val, err := r.client.Exists(ctx, key).Result()
			if err != nil {
				return err
			}
			exists = val > 0
			return nil
		},
		retry.Context(ctx),
		retry.Attempts(3),
		retry.DelayType(retry.BackOffDelay),
		retry.LastErrorOnly(true),
	)
	return exists, err
}

func (r *RedisCache) Set(ctx context.Context, key string, value string, expiration time.Duration) error {
	return retry.Do(
		func() error {
			return r.client.Set(ctx, key, value, expiration).Err()
		},
		retry.Context(ctx),
		retry.Attempts(3),
		retry.DelayType(retry.BackOffDelay),
		retry.LastErrorOnly(true),
	)
}

func (r *RedisCache) Incr(ctx context.Context, key string) (int64, error) {
	var count int64
	err := retry.Do(
		func() error {
			val, err := r.client.Incr(ctx, key).Result()
			if err != nil {
				return err
			}
			count = val
			return nil
		},
		retry.Context(ctx),
		retry.Attempts(3),
		retry.DelayType(retry.BackOffDelay),
		retry.LastErrorOnly(true),
	)
	return count, err
}
