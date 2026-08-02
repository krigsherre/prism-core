package http

import (
	"errors"
	"io"
	"net/http"
	"strings"

	"go.uber.org/zap"

	"api-gateway/internal/app"

	"go.opentelemetry.io/otel"
)

type IngressHandler struct {
	Facade app.IngressFacade
}

func NewIngressHandler(facade app.IngressFacade) *IngressHandler {
	return &IngressHandler{Facade: facade}
}

func (h *IngressHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	tracer := otel.Tracer("api-gateway")
	ctx, span := tracer.Start(ctx, "HandleUpload")
	defer span.End()

	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	tenantID := r.Header.Get("X-Tenant-ID")
	if tenantID == "" {
		http.Error(w, "X-Tenant-ID header is required", http.StatusBadRequest)
		return
	}

	reader, err := r.MultipartReader()
	if err != nil {
		http.Error(w, "Failed to parse multipart request", http.StatusBadRequest)
		return
	}

	for {
		part, err := reader.NextPart()
		if err != nil {
			if errors.Is(err, io.EOF) {
				break
			}
			zap.L().Error("Failed to parse multipart form", zap.Error(err), zap.String("tenant_id", tenantID))
			http.Error(w, "Failed to parse multipart form", http.StatusBadRequest)
			return
		}

		if part.FormName() == "file" {
			filename := part.FileName()
			if filename == "" {
				filename = "unknown.bin"
			}
			filename = strings.ReplaceAll(filename, "/", "_")
			err = h.Facade.ProcessUpload(ctx, tenantID, filename, part)
			if err != nil {
				zap.L().Error("Facade processing failed", zap.Error(err), zap.String("tenant_id", tenantID), zap.String("filename", filename))
				http.Error(w, "Internal server error", http.StatusInternalServerError)
				return
			}
			zap.L().Info("File successfully ingested", zap.String("tenant_id", tenantID), zap.String("filename", filename))
			w.WriteHeader(http.StatusAccepted)
			w.Write([]byte(`{"status":"accepted"}`))
			return
		}
	}

	http.Error(w, "No file provided in multipart form", http.StatusBadRequest)
}
