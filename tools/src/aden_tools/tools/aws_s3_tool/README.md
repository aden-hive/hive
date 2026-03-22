# AWS S3 Tool

Object storage operations via the S3 REST API with SigV4 request signing.

## Supported Actions

- **s3_list_buckets** – List all buckets in the account
- **s3_list_objects** – List objects in a bucket with optional prefix filter
- **s3_get_object** – Download an object (returns text content or base64 for binary)
- **s3_put_object** – Upload content to a key
- **s3_delete_object** – Delete an object
- **s3_copy_object** – Copy an object between keys or buckets
- **s3_get_object_metadata** – Retrieve object metadata (size, content type, last modified)
- **s3_generate_presigned_url** – Generate a time-limited presigned URL for sharing

## Setup

1. Create an IAM user or role with S3 permissions.

2. Set the required environment variables:
   ```bash
   export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
   export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
   export AWS_REGION=us-east-1
   ```

## Use Case

Example: "List all CSV files uploaded to the `data-ingestion/raw/` prefix today, download each one, and generate presigned URLs for the analytics team to review."
