"""
AWS S3 credentials.

Contains credentials for AWS S3 REST API with SigV4 signing.
Requires AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY.
"""

from .base import CredentialSpec

AWS_S3_CREDENTIALS = {
    "aws_access_key": CredentialSpec(
        env_var="AWS_ACCESS_KEY_ID",
        tools=[
            "s3_list_buckets",
            "s3_list_objects",
            "s3_get_object",
            "s3_put_object",
            "s3_delete_object",
            "s3_copy_object",
            "s3_get_object_metadata",
            "s3_generate_presigned_url",
        ],
        required=True,
        startup_required=False,
        help_url="https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html",
        description="AWS Access Key ID for S3 API access",
        direct_api_key_supported=True,
        api_key_instructions="""To set up AWS S3 API access:
1. Go to AWS IAM > Users > Security credentials
2. Create a new access key
3. Set environment variables:
   export AWS_ACCESS_KEY_ID=your-access-key-id
   export AWS_SECRET_ACCESS_KEY=your-secret-access-key
   export AWS_REGION=us-east-1""",
        health_check_endpoint="",
        credential_id="aws_access_key",
        credential_key="api_key",
        credential_group="aws",
    ),
    "aws_secret_key": CredentialSpec(
        env_var="AWS_SECRET_ACCESS_KEY",
        tools=[
            "s3_list_buckets",
            "s3_list_objects",
            "s3_get_object",
            "s3_put_object",
            "s3_delete_object",
            "s3_copy_object",
            "s3_get_object_metadata",
            "s3_generate_presigned_url",
        ],
        required=True,
        startup_required=False,
        help_url="https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html",
        description="AWS Secret Access Key for S3 API access",
        direct_api_key_supported=True,
        api_key_instructions="""See AWS_ACCESS_KEY_ID instructions above.""",
        health_check_endpoint="",
        credential_id="aws_secret_key",
        credential_key="api_key",
        credential_group="aws",
    ),
}
