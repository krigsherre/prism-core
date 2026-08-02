package domain

type TenantID string
type ETag string
type Bucket string
type Key string

type S3DiscoveryEvent struct {
	TenantID TenantID `json:"tenant_id"`
	Bucket   Bucket   `json:"bucket"`
	Key      Key      `json:"key"`
	ETag     ETag     `json:"etag"`
}
