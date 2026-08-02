package main

import (
	"context"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/sdk/resource"
	"go.opentelemetry.io/otel/sdk/trace"
	semconv "go.opentelemetry.io/otel/semconv/v1.24.0"
	"go.uber.org/zap"

	"s3-connector/internal/app"
	"s3-connector/internal/config"
	"s3-connector/internal/infrastructure/cache"
	"s3-connector/internal/infrastructure/db"
	"s3-connector/internal/infrastructure/gateway"
	"s3-connector/internal/infrastructure/kafka"
	"s3-connector/internal/infrastructure/s3"
)

func main() {
	logger, _ := zap.NewProduction()
	defer logger.Sync()
	zap.ReplaceGlobals(logger)

	ctx := context.Background()

	tp := initTracer(ctx)
	defer func() {
		if err := tp.Shutdown(ctx); err != nil {
			zap.L().Error("Error shutting down tracer provider", zap.Error(err))
		}
	}()

	cfg, err := config.Load()
	if err != nil {
		zap.L().Fatal("failed to load configuration", zap.Error(err))
	}

	s3Client, err := s3.NewS3Client(ctx, cfg.S3.Endpoint)
	if err != nil {
		zap.L().Fatal("failed to initialize s3 client", zap.Error(err))
	}

	kafkaConsumer := kafka.NewConsumer([]string{cfg.Kafka.Broker}, cfg.Kafka.Topic, cfg.Kafka.GroupID)
	defer kafkaConsumer.Close()

	redisCache := cache.NewRedisCache(cfg.Redis.Addr, cfg.App.LockTTL, cfg.App.CacheTTL)

	postgresDB, err := db.NewPostgresDB(cfg.Database.DSN, cfg.Database.MaxOpenConns, cfg.Database.MaxIdleConns)
	if err != nil {
		zap.L().Fatal("failed to initialize database", zap.Error(err))
	}
	defer postgresDB.Close()

	gatewayClient := gateway.NewGatewayClient(cfg.Gateway.URL)

	ingestor := app.NewIngestor(
		kafkaConsumer,
		s3Client,
		redisCache,
		postgresDB,
		gatewayClient,
		&cfg.App,
	)

	ingestor.Start(ctx)
}

func initTracer(ctx context.Context) *trace.TracerProvider {
	exporter, err := otlptracegrpc.New(ctx,
		otlptracegrpc.WithInsecure(),
		otlptracegrpc.WithEndpoint("otel-collector:4317"),
	)
	if err != nil {
		zap.L().Fatal("Failed to create trace exporter", zap.Error(err))
	}

	res, err := resource.New(ctx,
		resource.WithAttributes(
			semconv.ServiceName("s3-connector"),
		),
	)
	if err != nil {
		zap.L().Fatal("Failed to create resource", zap.Error(err))
	}

	tp := trace.NewTracerProvider(
		trace.WithBatcher(exporter),
		trace.WithResource(res),
	)
	otel.SetTracerProvider(tp)
	return tp
}
