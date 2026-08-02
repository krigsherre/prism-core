package gateway

import (
	"context"
	"fmt"
	"io"
	"mime/multipart"
	"net/http"

	"github.com/avast/retry-go/v4"
)

type GatewayClient struct {
	client *http.Client
	url    string
}

func NewGatewayClient(url string) *GatewayClient {
	return &GatewayClient{
		client: http.DefaultClient,
		url:    url,
	}
}

func (g *GatewayClient) PostFile(ctx context.Context, tenantID, filename string, stream io.Reader) error {
	data, err := io.ReadAll(stream)
	if err != nil {
		return fmt.Errorf("failed to read stream for gateway post: %w", err)
	}

	return retry.Do(
		func() error {
			pr, pw := io.Pipe()
			writer := multipart.NewWriter(pw)

			go func() {
				defer pw.Close()
				part, err := writer.CreateFormFile("file", filename)
				if err != nil {
					return
				}
				part.Write(data)
				writer.Close()
			}()

			req, err := http.NewRequestWithContext(ctx, http.MethodPost, g.url, pr)
			if err != nil {
				return retry.Unrecoverable(err)
			}
			req.Header.Set("Content-Type", writer.FormDataContentType())
			req.Header.Set("X-Tenant-ID", tenantID)

			resp, err := g.client.Do(req)
			if err != nil {
				return err
			}
			defer resp.Body.Close()

			if resp.StatusCode >= 500 {
				body, _ := io.ReadAll(resp.Body)
				return fmt.Errorf("gateway returned %d: %s", resp.StatusCode, string(body))
			} else if resp.StatusCode != http.StatusAccepted && resp.StatusCode != http.StatusOK {
				body, _ := io.ReadAll(resp.Body)
				return retry.Unrecoverable(fmt.Errorf("gateway returned unrecoverable error %d: %s", resp.StatusCode, string(body)))
			}

			return nil
		},
		retry.Context(ctx),
		retry.Attempts(3),
		retry.DelayType(retry.BackOffDelay),
		retry.LastErrorOnly(true),
	)
}
