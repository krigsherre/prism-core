package s3

import (
	"context"
	"fmt"
	"io"
	"time"

	"api-gateway/internal/config"
	"github.com/avast/retry-go/v4"
	"github.com/aws/aws-sdk-go-v2/aws"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/feature/s3/transfermanager"
	awss3 "github.com/aws/aws-sdk-go-v2/service/s3"
)

type Uploader interface {
	UploadStream(ctx context.Context, key string, body io.Reader) (string, error)
}

type s3Client struct {
	client *transfermanager.Client
	bucket string
}

func NewS3Client(ctx context.Context, cfg *config.Config) (Uploader, error) {
	awsCfg, err := awsconfig.LoadDefaultConfig(ctx, awsconfig.WithRegion(cfg.S3.Region))
	if err != nil {
		return nil, err
	}

	var s3Api *awss3.Client
	if cfg.S3.Endpoint != "" {
		s3Api = awss3.NewFromConfig(awsCfg, func(o *awss3.Options) {
			o.BaseEndpoint = aws.String(cfg.S3.Endpoint)
			o.UsePathStyle = true
		})
	} else {
		s3Api = awss3.NewFromConfig(awsCfg)
	}

	tmClient := transfermanager.New(s3Api)
	return &s3Client{client: tmClient, bucket: cfg.S3.Bucket}, nil
}

func (s *s3Client) UploadStream(ctx context.Context, key string, body io.Reader) (string, error) {
	var location string

	err := retry.Do(
		func() error {
			result, err := s.client.UploadObject(ctx, &transfermanager.UploadObjectInput{
				Bucket: aws.String(s.bucket),
				Key:    aws.String(key),
				Body:   body,
			})
			if err != nil {
				return err
			}
			if result.Location != nil {
				location = fmt.Sprintf("s3://%s/%s", s.bucket, key)
			}
			return nil
		},
		retry.Context(ctx),
		retry.Attempts(3),
		retry.Delay(500*time.Millisecond),
		retry.LastErrorOnly(true),
	)

	if err != nil {
		return "", err
	}
	return location, nil
}
