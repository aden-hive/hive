## AWS S3 Tool

Cloud object storage integration for the Hive Framework.

## Overview

The AWS S3 Tool provides cloud storage capabilities for agent workflows, including:

- File upload
- File download
- Object listing
- Object deletion
- Credential verification
This enables agents to store and retrieve artifacts, intermediate results, and generated outputs in S3.

## Installation

Install required dependencies:

```bash
uv add boto3 botocore
```

## Credential Configuration
1. Environment Variables (Recommended)

```bash
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
export AWS_DEFAULT_REGION=us-east-1
# Optional:
# export AWS_SESSION_TOKEN=your_session_token
```

2. IAM Role (Production Recommended)

When running on AWS infrastructure (EC2, ECS, Lambda, etc.), attach an IAM role with appropriate S3 permissions instead of using static credentials.

3. Hive Credential Store

The tool also supports Hive's CredentialStoreAdapter for secure credential management within agent workflows.

## Required IAM Permissions

Example IAM policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::your-bucket",
        "arn:aws:s3:::your-bucket/*"
      ]
    }
  ]
}
```

## MCP Tools
- s3_upload

Upload data to an S3 bucket.

Parameters:

1. bucket (str) — S3 bucket name
2. key (str) — Object key (file path)
3. data (str) — Content to upload
4. metadata (str, optional) — JSON string containing metadata
5. content_type (str, optional) — MIME type
6. base64_encoded (bool) — Whether data is base64 encoded

- s3_download

Download a file from S3.

Parameters:

1. bucket (str) — S3 bucket name
2. key (str) — Object key
3. version_id (str, optional) — Specific object version

- s3_list

List objects in an S3 bucket.

Parameters:

1. bucket (str) — S3 bucket name
2. prefix (str) — Filter by key prefix
3. max_keys (int) — Maximum number of objects to return

- s3_delete

Delete an object from S3.

Parameters:

1. bucket (str) — S3 bucket name
2. key (str) — Object key
3. version_id (str, optional) — Specific object version

## Testing

Run tests:

```bash
cd tools && uv run pytest tests/tools/test_s3_tool.py -v
```

## Error Handling

Common errors:

- NoSuchBucket — Bucket does not exist

- NoSuchKey — Object not found

- AccessDenied — Insufficient IAM permissions