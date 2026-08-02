package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"

	"go.uber.org/zap"

	"sqs-kafka-bridge/internal/app"
	"sqs-kafka-bridge/internal/config"
	"sqs-kafka-bridge/internal/infrastructure/aws"
	"sqs-kafka-bridge/internal/infrastructure/kafka"
)

func main() {
	logger, _ := zap.NewProduction()
	defer logger.Sync()

	cfg, err := config.LoadConfig()
	if err != nil {
		logger.Fatal("Failed to load configuration", zap.Error(err))
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, os.Interrupt, syscall.SIGTERM)
	go func() {
		sig := <-sigCh
		logger.Info("Received shutdown signal", zap.String("signal", sig.String()))
		cancel()
	}()

	sqsClient, err := aws.NewSQSAdapter(ctx, cfg)
	if err != nil {
		logger.Fatal("Failed to initialize SQS adapter", zap.Error(err))
	}

	kafkaProducer := kafka.NewKafkaProducer(cfg)
	defer kafkaProducer.Close()

	bridgeWorker := app.NewBridgeWorker(logger, sqsClient, kafkaProducer, &cfg.App)

	logger.Info("Starting SQS-Kafka Bridge Service", zap.String("queue", cfg.AWS.SQSQueueURL), zap.String("kafka", cfg.Kafka.Broker))

	bridgeWorker.Start(ctx)

	logger.Info("SQS-Kafka Bridge Service gracefully shut down.")
}
