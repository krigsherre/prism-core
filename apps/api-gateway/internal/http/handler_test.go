package http_test

import (
	"bytes"
	"context"
	"errors"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	apihttp "api-gateway/internal/http"

	"github.com/stretchr/testify/assert"
)

type mockFacade struct {
	processUploadFunc func(ctx context.Context, tenantID string, filename string, stream io.Reader) error
}

func (m *mockFacade) ProcessUpload(ctx context.Context, tenantID string, filename string, stream io.Reader) error {
	return m.processUploadFunc(ctx, tenantID, filename, stream)
}

func TestHandler_MethodNotAllowed(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/api/v1/upload", nil)
	rr := httptest.NewRecorder()

	handler := apihttp.NewIngressHandler(&mockFacade{})
	handler.ServeHTTP(rr, req)

	assert.Equal(t, http.StatusMethodNotAllowed, rr.Code)
}

func TestHandler_MissingTenantID(t *testing.T) {
	req := httptest.NewRequest(http.MethodPost, "/api/v1/upload", nil)
	rr := httptest.NewRecorder()

	handler := apihttp.NewIngressHandler(&mockFacade{})
	handler.ServeHTTP(rr, req)

	assert.Equal(t, http.StatusBadRequest, rr.Code)
	assert.Contains(t, rr.Body.String(), "X-Tenant-ID header is required")
}

func TestHandler_ValidUpload(t *testing.T) {
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	part, _ := writer.CreateFormFile("file", "test.pdf")
	part.Write([]byte("dummy content"))
	writer.Close()

	req := httptest.NewRequest(http.MethodPost, "/api/v1/upload", &body)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("X-Tenant-ID", "tenant-1")

	facade := &mockFacade{
		processUploadFunc: func(ctx context.Context, tenantID string, filename string, stream io.Reader) error {
			assert.Equal(t, "tenant-1", tenantID)
			assert.Equal(t, "test.pdf", filename)
			return nil
		},
	}

	rr := httptest.NewRecorder()
	handler := apihttp.NewIngressHandler(facade)
	handler.ServeHTTP(rr, req)

	assert.Equal(t, http.StatusAccepted, rr.Code)
	assert.Contains(t, rr.Body.String(), "accepted")
}

func TestHandler_FacadeError(t *testing.T) {
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	part, _ := writer.CreateFormFile("file", "test.pdf")
	part.Write([]byte("dummy content"))
	writer.Close()

	req := httptest.NewRequest(http.MethodPost, "/api/v1/upload", &body)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("X-Tenant-ID", "tenant-1")

	facade := &mockFacade{
		processUploadFunc: func(ctx context.Context, tenantID string, filename string, stream io.Reader) error {
			return errors.New("s3 upload failed")
		},
	}

	rr := httptest.NewRecorder()
	handler := apihttp.NewIngressHandler(facade)
	handler.ServeHTTP(rr, req)

	assert.Equal(t, http.StatusInternalServerError, rr.Code)
}

func TestHandler_InvalidMultipart(t *testing.T) {
	req := httptest.NewRequest(http.MethodPost, "/api/v1/upload", strings.NewReader("not a multipart body"))
	req.Header.Set("Content-Type", "multipart/form-data; boundary=missing")
	req.Header.Set("X-Tenant-ID", "tenant-1")
	rr := httptest.NewRecorder()

	handler := apihttp.NewIngressHandler(&mockFacade{})
	handler.ServeHTTP(rr, req)

	assert.Equal(t, http.StatusBadRequest, rr.Code)
	assert.Contains(t, rr.Body.String(), "No file provided")
}

func TestHandler_NoFilePart(t *testing.T) {
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	part, _ := writer.CreateFormField("other_field")
	part.Write([]byte("dummy content"))
	writer.Close()

	req := httptest.NewRequest(http.MethodPost, "/api/v1/upload", &body)
	req.Header.Set("Content-Type", writer.FormDataContentType())
	req.Header.Set("X-Tenant-ID", "tenant-1")
	rr := httptest.NewRecorder()

	handler := apihttp.NewIngressHandler(&mockFacade{})
	handler.ServeHTTP(rr, req)

	assert.Equal(t, http.StatusBadRequest, rr.Code)
	assert.Contains(t, rr.Body.String(), "No file provided in multipart form")
}

func TestHandler_NotMultipart(t *testing.T) {
	req := httptest.NewRequest(http.MethodPost, "/api/v1/upload", strings.NewReader(`{"json": true}`))
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Tenant-ID", "tenant-1")
	rr := httptest.NewRecorder()

	handler := apihttp.NewIngressHandler(&mockFacade{})
	handler.ServeHTTP(rr, req)

	assert.Equal(t, http.StatusBadRequest, rr.Code)
	assert.Contains(t, rr.Body.String(), "Failed to parse multipart request")
}
