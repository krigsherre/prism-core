package telemetry

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestInitTracer(t *testing.T) {
	ctx := context.Background()
	tp := InitTracer(ctx, "test-service")
	assert.NotNil(t, tp)
}
