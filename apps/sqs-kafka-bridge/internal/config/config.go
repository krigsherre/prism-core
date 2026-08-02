package config

import (
	"fmt"
	"strings"

	"github.com/spf13/viper"
)

type Config struct {
	App   AppConfig
	AWS   AWSConfig
	Kafka KafkaConfig
}

type AppConfig struct {
	MaxMessages int32
}

type AWSConfig struct {
	SQSQueueURL     string
	SQSEndpoint     string
	Region          string
	WaitTimeSeconds int32
}

type KafkaConfig struct {
	Broker string
	Topic  string
}

func LoadConfig() (*Config, error) {
	v := viper.New()
	v.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))
	v.AutomaticEnv()

	v.SetDefault("app.maxmessages", 10)
	v.SetDefault("aws.region", "us-east-1")
	v.SetDefault("aws.waittimeseconds", 20)
	v.SetDefault("kafka.topic", "s3_discovery_events")

	_ = v.BindEnv("app.maxmessages", "APP_MAXMESSAGES")
	_ = v.BindEnv("aws.sqsqueueurl", "SQS_QUEUE_URL")
	_ = v.BindEnv("aws.sqsendpoint", "SQS_ENDPOINT")
	_ = v.BindEnv("aws.region", "AWS_REGION")
	_ = v.BindEnv("aws.waittimeseconds", "AWS_WAITTIMESECONDS")
	_ = v.BindEnv("kafka.broker", "KAFKA_BROKER")
	_ = v.BindEnv("kafka.topic", "KAFKA_TOPIC")

	var cfg Config
	if err := v.Unmarshal(&cfg); err != nil {
		return nil, fmt.Errorf("failed to unmarshal config: %w", err)
	}

	if cfg.AWS.SQSQueueURL == "" {
		return nil, fmt.Errorf("SQS_QUEUE_URL is not set")
	}
	if cfg.Kafka.Broker == "" {
		return nil, fmt.Errorf("KAFKA_BROKER is not set")
	}

	return &cfg, nil
}
