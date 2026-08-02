package cache

import (
	"context"
	"testing"
	"time"

	"github.com/go-redis/redismock/v9"
)

func TestRedisCache_FilterNew(t *testing.T) {
	db, mock := redismock.NewClientMock()
	c := &RedisCache{
		client:   db,
		lockTTL:  5 * time.Minute,
		cacheTTL: 24 * time.Hour,
	}
	ctx := context.Background()

	etags := []string{"etag1", "etag2", "etag3"}

	mock.ExpectSetNX("etag1", "1", 5*time.Minute).SetVal(true)
	mock.ExpectSetNX("etag2", "1", 5*time.Minute).SetVal(false) // already exists
	mock.ExpectSetNX("etag3", "1", 5*time.Minute).SetVal(true)

	newEtags, err := c.FilterNew(ctx, etags)
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}

	if len(newEtags) != 2 {
		t.Fatalf("expected 2 new etags, got %d", len(newEtags))
	}
	if newEtags[0] != "etag1" || newEtags[1] != "etag3" {
		t.Fatalf("unexpected etags returned: %v", newEtags)
	}

	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("there were unfulfilled expectations: %s", err)
	}
}

func TestRedisCache_CacheEtags(t *testing.T) {
	db, mock := redismock.NewClientMock()
	c := &RedisCache{
		client:   db,
		lockTTL:  5 * time.Minute,
		cacheTTL: 24 * time.Hour,
	}
	ctx := context.Background()

	etags := []string{"etag1", "etag2"}

	mock.ExpectSet("etag1", "1", 24*time.Hour).SetVal("OK")
	mock.ExpectSet("etag2", "1", 24*time.Hour).SetVal("OK")

	err := c.CacheEtags(ctx, etags)
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}

	if err := mock.ExpectationsWereMet(); err != nil {
		t.Errorf("there were unfulfilled expectations: %s", err)
	}
}
