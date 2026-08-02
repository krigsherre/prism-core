package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"syscall"

	"triage-worker/internal/app"
	"triage-worker/internal/config"
	"triage-worker/internal/infrastructure/kafka"
	"triage-worker/internal/infrastructure/redis"

	"go.uber.org/zap"
)

func main() {
	logger, err := zap.NewProduction()
	if err != nil {
		log.Fatalf("Failed to initialize zap logger: %v", err)
	}
	defer logger.Sync()
	zap.ReplaceGlobals(logger)

	cfg, err := config.LoadConfig()
	if err != nil {
		logger.Fatal("Failed to load configuration", zap.Error(err))
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigs := make(chan os.Signal, 1)
	signal.Notify(sigs, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		<-sigs
		logger.Info("Shutting down worker...")
		cancel()
	}()

	rdb := redis.NewRedisCache(cfg)

	consumer := kafka.NewKafkaConsumer(cfg)
	defer consumer.Close()

	dlqProducer := kafka.NewKafkaProducer(cfg, cfg.Kafka.DLQTopic)
	defer dlqProducer.Close()

	gpuProducer := kafka.NewKafkaProducer(cfg, cfg.Kafka.GPUTopic)
	defer gpuProducer.Close()

	statusProducer := kafka.NewKafkaProducer(cfg, "document_status_events")
	defer statusProducer.Close()

	cleanupProducer := kafka.NewKafkaProducer(cfg, "s3_cleanup_tasks")
	defer cleanupProducer.Close()

	w := app.NewTriageWorker(logger, consumer, dlqProducer, gpuProducer, statusProducer, cleanupProducer, rdb, &cfg.App)

	w.Start(ctx)
}
