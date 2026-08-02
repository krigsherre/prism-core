package config

import (
	"os"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestLoadConfig_Defaults(t *testing.T) {
	os.Clearenv()

	cfg, err := LoadConfig()
	assert.NoError(t, err)
	assert.NotNil(t, cfg)

	assert.Equal(t, 100, cfg.App.Concurrency)
	assert.Equal(t, 3, cfg.App.MaxRetries)
	assert.Equal(t, "localhost:9092", cfg.Kafka.Broker)
	assert.Equal(t, "triage-worker-group", cfg.Kafka.ConsumerGroup)
	assert.Equal(t, "doc_ingest_events", cfg.Kafka.IngestTopic)
	assert.Equal(t, "doc_dlq", cfg.Kafka.DLQTopic)
	assert.Equal(t, "gpu_processing_queue", cfg.Kafka.GPUTopic)
	assert.Equal(t, "localhost:6379", cfg.Redis.Addr)
}

func TestLoadConfig_EnvVars(t *testing.T) {
	os.Clearenv()
	t.Setenv("KAFKA_BROKER", "kafka:9092")
	t.Setenv("REDIS_ADDR", "redis:6379")
	t.Setenv("APP_CONCURRENCY", "50")
	t.Setenv("APP_MAXRETRIES", "5")
	t.Setenv("KAFKA_CONSUMERGROUP", "custom-group")
	t.Setenv("KAFKA_INGESTTOPIC", "custom_ingest")
	t.Setenv("KAFKA_DLQTOPIC", "custom_dlq")
	t.Setenv("KAFKA_GPUTOPIC", "custom_gpu")

	cfg, err := LoadConfig()
	assert.NoError(t, err)

	assert.Equal(t, "kafka:9092", cfg.Kafka.Broker)
	assert.Equal(t, "redis:6379", cfg.Redis.Addr)
	assert.Equal(t, 50, cfg.App.Concurrency)
	assert.Equal(t, 5, cfg.App.MaxRetries)
	assert.Equal(t, "custom-group", cfg.Kafka.ConsumerGroup)
	assert.Equal(t, "custom_ingest", cfg.Kafka.IngestTopic)
	assert.Equal(t, "custom_dlq", cfg.Kafka.DLQTopic)
	assert.Equal(t, "custom_gpu", cfg.Kafka.GPUTopic)
}
