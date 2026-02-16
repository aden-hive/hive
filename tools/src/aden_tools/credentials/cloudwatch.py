"""AWS CloudWatch credential specification."""

from .base import CredentialSpec

CLOUDWATCH_CREDENTIALS = {
    "aws_cloudwatch": CredentialSpec(
        env_var="AWS_ACCESS_KEY_ID",
        tools=["cloudwatch_put_metric", "cloudwatch_put_log_event", "cloudwatch_create_alarm", "cloudwatch_get_metric_stats"],
        required=True,
        startup_required=False,
        help_url="https://console.aws.amazon.com/iam/",
        description="AWS access key ID for CloudWatch access. Also requires AWS_SECRET_ACCESS_KEY and optionally AWS_REGION.",
    )
}
