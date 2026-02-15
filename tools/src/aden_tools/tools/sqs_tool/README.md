# AWS SQS Toolkit

Native integration with AWS Simple Queue Service (SQS) for Hive agents.

## Overview
The SQS toolkit enables agents to manage message queues and handle message lifecycles (send, receive, delete), supporting asynchronous processing and resilient distributed workflows.

## Requirements
- `boto3` library
- AWS account with SQS permissions

## Configuration
Requires the following environment variables or credentials:
- `AWS_ACCESS_KEY_ID`: AWS Access Key.
- `AWS_SECRET_ACCESS_KEY`: AWS Secret Key.
- `AWS_REGION`: AWS Region (e.g., `us-east-1`).

## Available Tools

### Queue Management
- `sqs_create_queue`: Create standard or FIFO queues.
- `sqs_list_queues`: List all queue URLs in the region.
- `sqs_get_queue_attributes`: Retrieve queue metadata (message counts, etc.).
- `sqs_purge_queue`: Clear all messages from a queue.

### Message Operations
- `sqs_send_message`: Send a message to a queue (supports delay).
- `sqs_receive_messages`: Poll one or more messages (supports long polling).
- `sqs_delete_message`: Remove a message after successful processing.

## Setup Instructions
1. Get AWS credentials from the [IAM Console](https://console.aws.amazon.com/iam/home#/security_credentials).
2. Ensure user has `sqs:*` permissions.
3. Configure environment variables or use the Hive credential store.
