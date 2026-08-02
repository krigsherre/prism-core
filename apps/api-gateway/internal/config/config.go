package config

import (
	"fmt"
	"strings"

	"github.com/spf13/viper"
)

type Config struct {
	App   AppConfig
	Kafka KafkaConfig
	S3    S3Config
}

type AppConfig struct {
	Port string
}

type KafkaConfig struct {
	Broker string
	Topic  string
}

type S3Config struct {
	Region   string
	Endpoint string
	Bucket   string
}

func LoadConfig() (*Config, error) {
	v := viper.New()
	v.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))
	v.AutomaticEnv()

	v.SetDefault("app.port", "8080")
	v.SetDefault("kafka.broker", "localhost:9092")
	v.SetDefault("kafka.topic", "doc_ingest_events")
	v.SetDefault("s3.region", "us-east-1")
	v.SetDefault("s3.bucket", "prism-raw-documents")

	_ = v.BindEnv("app.port", "APP_PORT")
	_ = v.BindEnv("kafka.broker", "KAFKA_BROKER")
	// Dedicated ingest topic — do not share KAFKA_TOPIC with sqs-kafka-bridge.
	_ = v.BindEnv("kafka.topic", "KAFKA_INGESTTOPIC")
	_ = v.BindEnv("s3.region", "S3_REGION", "AWS_REGION")
	_ = v.BindEnv("s3.endpoint", "S3_ENDPOINT")
	_ = v.BindEnv("s3.bucket", "S3_BUCKET", "S3_BUCKET_NAME")

	var cfg Config
	if err := v.Unmarshal(&cfg); err != nil {
		return nil, fmt.Errorf("failed to unmarshal config: %w", err)
	}
	// AutomaticEnv maps kafka.topic → KAFKA_TOPIC (bridge discovery). Prefer ingest when set.
	if ingest := v.GetString("KAFKA_INGESTTOPIC"); ingest != "" {
		cfg.Kafka.Topic = ingest
	}
	return &cfg, nil
}
