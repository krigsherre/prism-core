package config

import (
	"os"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestLoadConfig_RequiresQueueAndBroker(t *testing.T) {
	os.Clearenv()
	_, err := LoadConfig()
	assert.Error(t, err)
}

func TestLoadConfig_Defaults(t *testing.T) {
	os.Clearenv()
	t.Setenv("SQS_QUEUE_URL", "http://localhost:9324/queue/test")
	t.Setenv("KAFKA_BROKER", "localhost:9092")

	cfg, err := LoadConfig()
	if !assert.NoError(t, err) {
		return
	}

	assert.Equal(t, "localhost:9092", cfg.Kafka.Broker)
	assert.Equal(t, "http://localhost:9324/queue/test", cfg.AWS.SQSQueueURL)
	assert.Equal(t, "s3_discovery_events", cfg.Kafka.Topic)
	assert.Equal(t, int32(10), cfg.App.MaxMessages)
	assert.Equal(t, int32(20), cfg.AWS.WaitTimeSeconds)
	assert.Equal(t, "us-east-1", cfg.AWS.Region)
}

func TestLoadConfig_EnvVars(t *testing.T) {
	os.Clearenv()
	t.Setenv("SQS_QUEUE_URL", "http://aws/queue/test")
	t.Setenv("KAFKA_BROKER", "kafka:9092")
	t.Setenv("KAFKA_TOPIC", "custom_topic")
	t.Setenv("AWS_REGION", "eu-west-1")
	t.Setenv("SQS_ENDPOINT", "http://elasticmq:9324")
	t.Setenv("APP_MAXMESSAGES", "25")

	cfg, err := LoadConfig()
	if !assert.NoError(t, err) {
		return
	}

	assert.Equal(t, "kafka:9092", cfg.Kafka.Broker)
	assert.Equal(t, "custom_topic", cfg.Kafka.Topic)
	assert.Equal(t, "http://aws/queue/test", cfg.AWS.SQSQueueURL)
	assert.Equal(t, "eu-west-1", cfg.AWS.Region)
	assert.Equal(t, "http://elasticmq:9324", cfg.AWS.SQSEndpoint)
	assert.Equal(t, int32(25), cfg.App.MaxMessages)
}
