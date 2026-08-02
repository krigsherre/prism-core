package middleware

import (
	"net/http"

	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
)

func Telemetry(next http.Handler, operation string) http.Handler {
	return otelhttp.NewHandler(next, operation)
}
