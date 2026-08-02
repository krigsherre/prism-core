package cache

import (
	"context"
	"time"

	"github.com/redis/go-redis/v9"
)

type RedisCache struct {
	client   *redis.Client
	lockTTL  time.Duration
	cacheTTL time.Duration
}

func NewRedisCache(redisAddr string, lockTTL, cacheTTL time.Duration) *RedisCache {
	client := redis.NewClient(&redis.Options{
		Addr: redisAddr,
	})
	return &RedisCache{
		client:   client,
		lockTTL:  lockTTL,
		cacheTTL: cacheTTL,
	}
}

func (c *RedisCache) FilterNew(ctx context.Context, etags []string) ([]string, error) {
	if len(etags) == 0 {
		return nil, nil
	}

	pipe := c.client.Pipeline()
	var cmds []*redis.BoolCmd
	for _, etag := range etags {
		cmds = append(cmds, pipe.SetNX(ctx, etag, "1", c.lockTTL))
	}

	if _, err := pipe.Exec(ctx); err != nil {
		return nil, err
	}

	var newEtags []string
	for i, cmd := range cmds {
		if cmd.Val() {
			newEtags = append(newEtags, etags[i])
		}
	}
	return newEtags, nil
}

func (c *RedisCache) CacheEtags(ctx context.Context, etags []string) error {
	if len(etags) == 0 {
		return nil
	}

	pipe := c.client.Pipeline()
	for _, etag := range etags {
		pipe.Set(ctx, etag, "1", c.cacheTTL)
	}
	_, err := pipe.Exec(ctx)
	return err
}
