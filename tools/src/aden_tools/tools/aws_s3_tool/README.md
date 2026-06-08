# AWS S3 Tool

Manage Amazon S3 buckets and objects using AWS Signature V4 authentication.

## Tools

| Tool | Description |
|------|-------------|
| `s3_list_buckets` | List all S3 buckets in the account |
| `s3_list_objects` | List objects in a bucket with optional prefix filter |
| `s3_get_object` | Download an object's content (text or base64) |
| `s3_put_object` | Upload content to an S3 object |
| `s3_delete_object` | Delete an object from a bucket |
| `s3_copy_object` | Copy an object between buckets or keys |
| `s3_get_object_metadata` | Get object metadata (size, content type, ETag) |
| `s3_generate_presigned_url` | Generate a pre-signed URL for temporary access |

## Setup

Set the following environment variables:

| Variable | Description |
|----------|-------------|
| `AWS_ACCESS_KEY_ID` | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | AWS secret key |
| `AWS_REGION` | AWS region (default: `us-east-1`) |

Get credentials at: [AWS Console](https://console.aws.amazon.com/iam/)

## Usage Examples

### List buckets
```python
s3_list_buckets()
```

### List objects with prefix
```python
s3_list_objects(bucket="my-bucket", prefix="data/", max_keys=20)
```

### Upload a file
```python
s3_put_object(bucket="my-bucket", key="reports/q1.csv", content="col1,col2\n1,2")
```

### Generate a pre-signed URL
```python
s3_generate_presigned_url(bucket="my-bucket", key="file.pdf", expires_in=3600)
```

## Error Handling

All tools return error dicts on failure:
```python
{"error": "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are required", "help": "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables"}
{"error": "HTTP 404: <NoSuchKey>...</NoSuchKey>"}
{"error": "Request timed out"}
```
