package config

import (
	"os"
	"testing"
	"time"
)

func TestLoadConfig_Defaults(t *testing.T) {
	os.Clearenv()

	cfg, err := Load()
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}

	if cfg.Kafka.Broker != "localhost:9092" {
		t.Errorf("expected localhost:9092, got %s", cfg.Kafka.Broker)
	}
	if cfg.App.MaxBatchSize != 500 {
		t.Errorf("expected 500, got %d", cfg.App.MaxBatchSize)
	}
	if cfg.App.LockTTL != 5*time.Minute {
		t.Errorf("expected 5m, got %v", cfg.App.LockTTL)
	}
}

func TestLoadConfig_EnvVars(t *testing.T) {
	os.Clearenv()
	t.Setenv("KAFKA_BROKER", "kafka:9092")
	t.Setenv("REDIS_ADDR", "redis:6379")
	t.Setenv("POSTGRES_DSN", "postgres://user:pass@db:5432/prism?sslmode=disable")
	t.Setenv("GATEWAY_URL", "http://api-gateway:8080/api/v1/upload")
	t.Setenv("S3_ENDPOINT", "http://s3mock:9090")
	t.Setenv("APP_MAXBATCHSIZE", "100")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}

	if cfg.Kafka.Broker != "kafka:9092" {
		t.Errorf("expected kafka:9092, got %s", cfg.Kafka.Broker)
	}
	if cfg.Redis.Addr != "redis:6379" {
		t.Errorf("expected redis:6379, got %s", cfg.Redis.Addr)
	}
	if cfg.Database.DSN != "postgres://user:pass@db:5432/prism?sslmode=disable" {
		t.Errorf("unexpected DSN: %s", cfg.Database.DSN)
	}
	if cfg.Gateway.URL != "http://api-gateway:8080/api/v1/upload" {
		t.Errorf("unexpected gateway URL: %s", cfg.Gateway.URL)
	}
	if cfg.S3.Endpoint != "http://s3mock:9090" {
		t.Errorf("unexpected S3 endpoint: %s", cfg.S3.Endpoint)
	}
	if cfg.App.MaxBatchSize != 100 {
		t.Errorf("expected 100, got %d", cfg.App.MaxBatchSize)
	}
}
