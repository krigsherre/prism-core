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

	assert.Equal(t, "8080", cfg.App.Port)
	assert.Equal(t, "localhost:9092", cfg.Kafka.Broker)
	assert.Equal(t, "doc_ingest_events", cfg.Kafka.Topic)
	assert.Equal(t, "us-east-1", cfg.S3.Region)
	assert.Equal(t, "prism-raw-documents", cfg.S3.Bucket)
}

func TestLoadConfig_EnvVars(t *testing.T) {
	os.Clearenv()
	t.Setenv("KAFKA_BROKER", "kafka:9092")
	t.Setenv("S3_REGION", "eu-west-1")
	t.Setenv("APP_PORT", "9090")
	t.Setenv("KAFKA_INGESTTOPIC", "custom_ingest")
	t.Setenv("KAFKA_TOPIC", "s3_discovery_events")
	t.Setenv("S3_ENDPOINT", "http://s3mock:9090")
	t.Setenv("S3_BUCKET", "raw")

	cfg, err := LoadConfig()
	assert.NoError(t, err)

	assert.Equal(t, "kafka:9092", cfg.Kafka.Broker)
	assert.Equal(t, "eu-west-1", cfg.S3.Region)
	assert.Equal(t, "9090", cfg.App.Port)
	assert.Equal(t, "custom_ingest", cfg.Kafka.Topic)
	assert.Equal(t, "http://s3mock:9090", cfg.S3.Endpoint)
	assert.Equal(t, "raw", cfg.S3.Bucket)
}
