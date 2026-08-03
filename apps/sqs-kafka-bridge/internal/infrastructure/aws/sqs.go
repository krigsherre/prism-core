package aws

import (
	"context"

	cfg "sqs-kafka-bridge/internal/config"

	"github.com/avast/retry-go/v4"
	aws_sdk "github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
	"github.com/aws/aws-sdk-go-v2/service/sqs/types"
)

type SQSClient interface {
	ReceiveMessages(ctx context.Context, maxMessages int32) ([]types.Message, error)
	DeleteMessage(ctx context.Context, receiptHandle string) error
}

type SQSAPI interface {
	ReceiveMessage(ctx context.Context, params *sqs.ReceiveMessageInput, optFns ...func(*sqs.Options)) (*sqs.ReceiveMessageOutput, error)
	DeleteMessage(ctx context.Context, params *sqs.DeleteMessageInput, optFns ...func(*sqs.Options)) (*sqs.DeleteMessageOutput, error)
}

type SQSAdapter struct {
	client          SQSAPI
	queueURL        string
	waitTimeSeconds int32
}

func NewSQSAdapter(ctx context.Context, appConfig *cfg.Config) (*SQSAdapter, error) {
	awsCfg, err := config.LoadDefaultConfig(ctx,
		config.WithRegion(appConfig.AWS.Region),
		config.WithCredentialsProvider(credentials.NewStaticCredentialsProvider("test", "test", "")),
	)
	if err != nil {
		return nil, err
	}

	var sqsClient *sqs.Client
	if appConfig.AWS.SQSEndpoint != "" {
		awsCfg.BaseEndpoint = aws_sdk.String(appConfig.AWS.SQSEndpoint)
	}
	sqsClient = sqs.NewFromConfig(awsCfg)

	return &SQSAdapter{
		client:          sqsClient,
		queueURL:        appConfig.AWS.SQSQueueURL,
		waitTimeSeconds: appConfig.AWS.WaitTimeSeconds,
	}, nil
}

func (s *SQSAdapter) ReceiveMessages(ctx context.Context, maxMessages int32) ([]types.Message, error) {
	var messages []types.Message
	err := retry.Do(
		func() error {
			params := &sqs.ReceiveMessageInput{
				QueueUrl:            aws_sdk.String(s.queueURL),
				MaxNumberOfMessages: maxMessages,
				WaitTimeSeconds:     s.waitTimeSeconds,
			}

			resp, err := s.client.ReceiveMessage(ctx, params)
			if err != nil {
				return err
			}
			messages = resp.Messages
			return nil
		},
		retry.Context(ctx),
		retry.Attempts(3),
		retry.DelayType(retry.BackOffDelay),
		retry.LastErrorOnly(true),
	)

	if err != nil {
		return nil, err
	}
	return messages, nil
}

func (s *SQSAdapter) DeleteMessage(ctx context.Context, receiptHandle string) error {
	return retry.Do(
		func() error {
			_, err := s.client.DeleteMessage(ctx, &sqs.DeleteMessageInput{
				QueueUrl:      aws_sdk.String(s.queueURL),
				ReceiptHandle: aws_sdk.String(receiptHandle),
			})
			return err
		},
		retry.Context(ctx),
		retry.Attempts(3),
		retry.DelayType(retry.BackOffDelay),
		retry.LastErrorOnly(true),
	)
}
