package routing

import (
	"context"
	"testing"

	prismv1 "contracts/gen/go/proto/prism/v1"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/mock"
)

type MockProducer struct {
	mock.Mock
}

func (m *MockProducer) PublishMessage(ctx context.Context, key, value []byte) error {
	args := m.Called(ctx, key, value)
	return args.Error(0)
}

func (m *MockProducer) Close() error {
	args := m.Called()
	return args.Error(0)
}

func TestGpuRouteStrategy(t *testing.T) {
	mockProducer := new(MockProducer)
	strategy := NewGpuRouteStrategy(mockProducer)

	ctx := context.Background()
	event := &prismv1.IngestEvent{TenantId: "tenant-1", EventId: "evt-1"}

	mockProducer.On("PublishMessage", ctx, []byte("tenant-1"), mock.Anything).Return(nil).Once()
	
	err := strategy.Route(ctx, event)
	assert.NoError(t, err)
	
	mockProducer.AssertExpectations(t)
}

