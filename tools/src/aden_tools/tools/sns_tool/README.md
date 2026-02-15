# AWS SNS Toolkit

Native integration with AWS Simple Notification Service (SNS) for Hive agents.

## Overview
The SNS toolkit allows agents to create topics, publish messages, and manage subscriptions, enabling event-driven orchestration and multi-channel notifications (Email, SMS, Lambda).

## Requirements
- `boto3` library
- AWS account with SNS permissions

## Configuration
Requires the following environment variables or credentials:
- `AWS_ACCESS_KEY_ID`: AWS Access Key.
- `AWS_SECRET_ACCESS_KEY`: AWS Secret Key.
- `AWS_REGION`: AWS Region (e.g., `us-east-1`).

## Available Tools

### Topic Management
- `sns_create_topic`: Create a new notification topic.
- `sns_list_topics`: List all available topic ARNs.
- `sns_delete_topic`: Remove a topic and its subscriptions.

### Messaging & Publishing
- `sns_publish_message`: Send a message to a topic ARN or directly to a phone number (SMS).
- `sns_list_subscriptions_by_topic`: Check who is receiving alerts for a topic.

### Subscription Management
- `sns_subscribe_endpoint`: Add an endpoint (email, sms, sqs, lambda) to a topic.
- `sns_unsubscribe`: Remove a subscription.

## Setup Instructions
1. Get AWS credentials from the [IAM Console](https://console.aws.amazon.com/iam/home#/security_credentials).
2. Ensure user has `sns:*` permissions.
3. Configure environment variables or use the Hive credential store.
