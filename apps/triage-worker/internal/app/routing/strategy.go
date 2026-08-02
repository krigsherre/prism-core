package routing

import (
	"context"
	"fmt"
	"log"

	prismv1 "contracts/gen/go/proto/prism/v1"
	"triage-worker/internal/infrastructure/kafka"

	"google.golang.org/protobuf/proto"
)

type RoutingStrategy interface {
	Route(ctx context.Context, event *prismv1.IngestEvent) error
}

type GpuRouteStrategy struct {
	producer kafka.Producer
}

func NewGpuRouteStrategy(producer kafka.Producer) *GpuRouteStrategy {
	return &GpuRouteStrategy{
		producer: producer,
	}
}

func (s *GpuRouteStrategy) Route(ctx context.Context, event *prismv1.IngestEvent) error {
	log.Printf("[GpuRoute] Routing document %s to gpu processing queue", event.EventId)

	val, err := proto.Marshal(event)
	if err != nil {
		return fmt.Errorf("failed to marshal event %s: %w", event.EventId, err)
	}

	if err := s.producer.PublishMessage(ctx, []byte(event.TenantId), val); err != nil {
		return fmt.Errorf("failed to write event %s to kafka: %w", event.EventId, err)
	}

	return nil
}
