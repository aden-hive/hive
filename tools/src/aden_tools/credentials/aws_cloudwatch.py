"""
AWS CloudWatch credentials.

Contains credentials for the AWS CloudWatch Query API and CloudWatch Logs
JSON API with SigV4 signing. Requires AWS_ACCESS_KEY_ID and
AWS_SECRET_ACCESS_KEY (AWS_REGION defaults to us-east-1).
"""

from .base import CredentialSpec

_CLOUDWATCH_TOOLS = [
    "cloudwatch_list_metrics",
    "cloudwatch_get_metric_statistics",
    "cloudwatch_list_alarms",
    "cloudwatch_start_logs_query",
    "cloudwatch_get_query_results",
]

AWS_CLOUDWATCH_CREDENTIALS = {
    "aws_cloudwatch_access_key": CredentialSpec(
        env_var="AWS_ACCESS_KEY_ID",
        tools=_CLOUDWATCH_TOOLS,
        required=True,
        startup_required=False,
        help_url="https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html",
        description="AWS Access Key ID for CloudWatch API access",
        direct_api_key_supported=True,
        api_key_instructions="""To set up AWS CloudWatch API access:
1. Go to AWS IAM > Users > Security credentials
2. Create a new access key
3. Attach an IAM policy granting cloudwatch:ListMetrics, cloudwatch:GetMetricStatistics,
   cloudwatch:DescribeAlarms, logs:StartQuery, logs:GetQueryResults
4. Set environment variables:
   export AWS_ACCESS_KEY_ID=your-access-key-id
   export AWS_SECRET_ACCESS_KEY=your-secret-access-key
   export AWS_REGION=us-east-1""",
        health_check_endpoint="",
        credential_id="aws_cloudwatch_access_key",
        credential_key="api_key",
        credential_group="aws",
    ),
    "aws_cloudwatch_secret_key": CredentialSpec(
        env_var="AWS_SECRET_ACCESS_KEY",
        tools=_CLOUDWATCH_TOOLS,
        required=True,
        startup_required=False,
        help_url="https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html",
        description="AWS Secret Access Key for CloudWatch API access",
        direct_api_key_supported=True,
        api_key_instructions="""See AWS_ACCESS_KEY_ID instructions above.""",
        health_check_endpoint="",
        credential_id="aws_cloudwatch_secret_key",
        credential_key="api_key",
        credential_group="aws",
    ),
}
