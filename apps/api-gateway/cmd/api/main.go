package main

import (
	"context"
	"net/http"

	"go.uber.org/zap"

	"api-gateway/internal/app"
	"api-gateway/internal/config"
	apihttp "api-gateway/internal/http"
	"api-gateway/internal/http/middleware"
	"api-gateway/internal/infrastructure/kafka"
	"api-gateway/internal/infrastructure/s3"
	"api-gateway/internal/infrastructure/telemetry"
)

func main() {
	logger, _ := zap.NewProduction()
	defer logger.Sync()
	zap.ReplaceGlobals(logger)

	ctx := context.Background()
	cfg, err := config.LoadConfig()
	if err != nil {
		zap.L().Fatal("Failed to load configuration", zap.Error(err))
	}

	tp := telemetry.InitTracer(ctx, "api-gateway")
	defer func() {
		if err := tp.Shutdown(ctx); err != nil {
			zap.L().Error("Error shutting down tracer provider", zap.Error(err))
		}
	}()
	s3Client, err := s3.NewS3Client(ctx, cfg)
	if err != nil {
		zap.L().Fatal("Failed to init S3", zap.Error(err))
	}

	kafkaClient := kafka.NewKafkaPublisher(cfg)
	defer kafkaClient.Close()
	facade := app.NewIngressFacade(s3Client, kafkaClient)
	uploadHandler := apihttp.NewIngressHandler(facade)
	mux := http.NewServeMux()
	mux.Handle("/api/v1/upload", uploadHandler)
	handler := middleware.SecurityHeaders(
		middleware.CORS(
			middleware.RequestLogger(
				middleware.Telemetry(mux, "api-gateway"),
			),
		),
	)

	zap.L().Info("Starting API Gateway", zap.String("port", cfg.App.Port))
	if err := http.ListenAndServe(":"+cfg.App.Port, handler); err != nil {
		zap.L().Fatal("Server failed", zap.Error(err))
	}
}
