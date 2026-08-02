package config

import (
	"fmt"
	"strings"

	"github.com/spf13/viper"
)

type Config struct {
	App   AppConfig
	Kafka KafkaConfig
	Redis RedisConfig
}

type AppConfig struct {
	Concurrency int
	MaxRetries  int
}

type KafkaConfig struct {
	Broker          string
	ConsumerGroup   string
	IngestTopic     string
	DLQTopic        string
	GPUTopic        string
	MinBytes        int
	MaxBytes        int
	CommitIntervals string
}

type RedisConfig struct {
	Addr string
}

func LoadConfig() (*Config, error) {
	v := viper.New()
	v.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))
	v.AutomaticEnv()

	v.SetDefault("app.concurrency", 100)
	v.SetDefault("app.maxretries", 3)
	v.SetDefault("kafka.broker", "localhost:9092")
	v.SetDefault("kafka.consumergroup", "triage-worker-group")
	v.SetDefault("kafka.ingesttopic", "doc_ingest_events")
	v.SetDefault("kafka.dlqtopic", "doc_dlq")
	v.SetDefault("kafka.gputopic", "gpu_processing_queue")
	v.SetDefault("kafka.minbytes", 10e3)
	v.SetDefault("kafka.maxbytes", 10e6)
	v.SetDefault("kafka.commitintervals", "1s")
	v.SetDefault("redis.addr", "localhost:6379")

	_ = v.BindEnv("app.concurrency", "APP_CONCURRENCY")
	_ = v.BindEnv("app.maxretries", "APP_MAXRETRIES")
	_ = v.BindEnv("kafka.broker", "KAFKA_BROKER")
	_ = v.BindEnv("kafka.consumergroup", "KAFKA_CONSUMERGROUP")
	_ = v.BindEnv("kafka.ingesttopic", "KAFKA_INGESTTOPIC")
	_ = v.BindEnv("kafka.dlqtopic", "KAFKA_DLQTOPIC")
	_ = v.BindEnv("kafka.gputopic", "KAFKA_GPUTOPIC")
	_ = v.BindEnv("kafka.minbytes", "KAFKA_MINBYTES")
	_ = v.BindEnv("kafka.maxbytes", "KAFKA_MAXBYTES")
	_ = v.BindEnv("kafka.commitintervals", "KAFKA_COMMITINTERVALS")
	_ = v.BindEnv("redis.addr", "REDIS_ADDR")

	var cfg Config
	if err := v.Unmarshal(&cfg); err != nil {
		return nil, fmt.Errorf("failed to unmarshal config: %w", err)
	}
	return &cfg, nil
}
