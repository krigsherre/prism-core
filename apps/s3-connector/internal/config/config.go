package config

import (
	"fmt"
	"strings"
	"time"

	"github.com/spf13/viper"
)

type Config struct {
	Kafka    KafkaConfig
	Redis    RedisConfig
	Database DatabaseConfig
	S3       S3Config
	Gateway  GatewayConfig
	App      AppConfig
}

type KafkaConfig struct {
	Broker  string
	Topic   string
	GroupID string
}

type RedisConfig struct {
	Addr string
}

type DatabaseConfig struct {
	DSN          string
	MaxOpenConns int
	MaxIdleConns int
}

type S3Config struct {
	Endpoint string
}

type GatewayConfig struct {
	URL string
}

type AppConfig struct {
	MaxBatchSize int
	FetchTimeout time.Duration
	LockTTL      time.Duration
	CacheTTL     time.Duration
}

func Load() (*Config, error) {
	v := viper.New()
	v.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))
	v.AutomaticEnv()

	v.SetDefault("kafka.broker", "localhost:9092")
	v.SetDefault("kafka.topic", "s3_discovery_events")
	v.SetDefault("kafka.groupid", "ingestor_group")
	v.SetDefault("redis.addr", "localhost:6379")
	v.SetDefault("database.dsn", "postgres://postgres:postgres@localhost:5432/prism?sslmode=disable")
	v.SetDefault("database.maxopenconns", 50)
	v.SetDefault("database.maxidleconns", 20)
	v.SetDefault("gateway.url", "http://localhost:8080/api/v1/upload")
	v.SetDefault("app.maxbatchsize", 500)
	v.SetDefault("app.fetchtimeout", 1*time.Second)
	v.SetDefault("app.lockttl", 5*time.Minute)
	v.SetDefault("app.cachettl", 24*time.Hour)

	// Canonical env names used by compose / .env (BindEnv so Unmarshal sees them).
	_ = v.BindEnv("kafka.broker", "KAFKA_BROKER")
	_ = v.BindEnv("kafka.topic", "KAFKA_TOPIC")
	_ = v.BindEnv("kafka.groupid", "KAFKA_GROUPID")
	_ = v.BindEnv("redis.addr", "REDIS_ADDR")
	_ = v.BindEnv("database.dsn", "POSTGRES_DSN", "DATABASE_DSN")
	_ = v.BindEnv("database.maxopenconns", "DATABASE_MAXOPENCONNS")
	_ = v.BindEnv("database.maxidleconns", "DATABASE_MAXIDLECONNS")
	_ = v.BindEnv("gateway.url", "GATEWAY_URL")
	_ = v.BindEnv("s3.endpoint", "S3_ENDPOINT")
	_ = v.BindEnv("app.maxbatchsize", "APP_MAXBATCHSIZE")
	_ = v.BindEnv("app.fetchtimeout", "APP_FETCHTIMEOUT")
	_ = v.BindEnv("app.lockttl", "APP_LOCKTTL")
	_ = v.BindEnv("app.cachettl", "APP_CACHETTL")

	var cfg Config
	if err := v.Unmarshal(&cfg); err != nil {
		return nil, fmt.Errorf("failed to unmarshal config: %w", err)
	}
	return &cfg, nil
}
