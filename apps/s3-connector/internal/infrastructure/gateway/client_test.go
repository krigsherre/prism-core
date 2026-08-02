package gateway

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestGatewayClient_PostFile_Success(t *testing.T) {
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-Tenant-ID") != "tenant1" {
			t.Errorf("expected tenant1, got %s", r.Header.Get("X-Tenant-ID"))
		}
		w.WriteHeader(http.StatusAccepted)
	}))
	defer ts.Close()

	client := NewGatewayClient(ts.URL)
	err := client.PostFile(context.Background(), "tenant1", "test.txt", strings.NewReader("hello world"))
	if err != nil {
		t.Fatalf("expected no error, got %v", err)
	}
}

func TestGatewayClient_PostFile_RetryAndFail(t *testing.T) {
	attempts := 0
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		attempts++
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer ts.Close()

	client := NewGatewayClient(ts.URL)
	err := client.PostFile(context.Background(), "tenant1", "test.txt", strings.NewReader("hello world"))
	if err == nil {
		t.Fatalf("expected error, got nil")
	}
	if attempts != 3 {
		t.Errorf("expected 3 attempts, got %d", attempts)
	}
}
