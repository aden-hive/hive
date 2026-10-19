"""
Amazon Redshift Data API credentials.

Contains credentials for the Redshift Data API with SigV4 signing.
Reuses AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY.
"""

from .base import CredentialSpec

REDSHIFT_CREDENTIALS = {
    "redshift_access_key": CredentialSpec(
        env_var="AWS_ACCESS_KEY_ID",
        tools=[
            "redshift_execute_sql",
            "redshift_describe_statement",
            "redshift_get_results",
            "redshift_list_databases",
            "redshift_list_tables",
        ],
        required=True,
        startup_required=False,
        help_url="https://docs.aws.amazon.com/redshift/latest/mgmt/data-api.html",
        description="AWS Access Key ID for Redshift Data API access",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Redshift Data API access:
1. Ensure your IAM user has redshift-data:* permissions
2. Set environment variables:
   export AWS_ACCESS_KEY_ID=your-access-key-id
   export AWS_SECRET_ACCESS_KEY=your-secret-access-key
   export AWS_REGION=us-east-1""",
        health_check_endpoint="",
        credential_id="redshift_access_key",
        credential_key="api_key",
        credential_group="aws",
    ),
    "redshift_secret_key": CredentialSpec(
        env_var="AWS_SECRET_ACCESS_KEY",
        tools=[
            "redshift_execute_sql",
            "redshift_describe_statement",
            "redshift_get_results",
            "redshift_list_databases",
            "redshift_list_tables",
        ],
        required=True,
        startup_required=False,
        help_url="https://docs.aws.amazon.com/redshift/latest/mgmt/data-api.html",
        description="AWS Secret Access Key for Redshift Data API access",
        direct_api_key_supported=True,
        api_key_instructions="""See AWS_ACCESS_KEY_ID instructions above.""",
        health_check_endpoint="",
        credential_id="redshift_secret_key",
        credential_key="api_key",
        credential_group="aws",
    ),
}
