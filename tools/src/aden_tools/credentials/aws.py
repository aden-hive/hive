"""AWS credentials.

Contains credentials for AWS services like SNS and SQS.
"""

from .base import CredentialSpec

AWS_TOOLS = [
    "sns_create_topic",
    "sns_list_topics",
    "sns_delete_topic",
    "sns_publish_message",
    "sns_list_subscriptions_by_topic",
    "sns_subscribe_endpoint",
    "sns_unsubscribe",
    "sqs_create_queue",
    "sqs_list_queues",
    "sqs_get_queue_attributes",
    "sqs_send_message",
    "sqs_receive_messages",
    "sqs_delete_message",
    "sqs_purge_queue",
]

AWS_CREDENTIALS = {
    "aws_access_key_id": CredentialSpec(
        env_var="AWS_ACCESS_KEY_ID",
        tools=AWS_TOOLS,
        required=True,
        startup_required=False,
        help_url="https://console.aws.amazon.com/iam/home#/security_credentials",
        description="AWS Access Key ID",
        direct_api_key_supported=True,
        api_key_instructions="""To get AWS credentials:
1. Sign in to the AWS Management Console.
2. Go to IAM > Users > [Your User].
3. Go to Security credentials > Access keys.
4. Click 'Create access key' and copy the Access Key ID.""",
        credential_id="aws_access_key_id",
        credential_key="access_key_id",
        credential_group="aws",
    ),
    "aws_secret_access_key": CredentialSpec(
        env_var="AWS_SECRET_ACCESS_KEY",
        tools=AWS_TOOLS,
        required=True,
        startup_required=False,
        help_url="https://console.aws.amazon.com/iam/home#/security_credentials",
        description="AWS Secret Access Key",
        direct_api_key_supported=True,
        api_key_instructions="""To get AWS credentials:
1. Sign in to the AWS Management Console.
2. Go to IAM > Users > [Your User].
3. Go to Security credentials > Access keys.
4. Click 'Create access key' and copy the Secret Access Key.""",
        credential_id="aws_secret_access_key",
        credential_key="secret_access_key",
        credential_group="aws",
    ),
    "aws_region": CredentialSpec(
        env_var="AWS_REGION",
        tools=AWS_TOOLS,
        required=True,
        startup_required=False,
        help_url="https://docs.aws.amazon.com/general/latest/gr/rande.html",
        description="AWS Region (e.g., us-east-1)",
        direct_api_key_supported=True,
        api_key_instructions="Select the AWS region you want to use (e.g., 'us-east-1', 'eu-west-1').",
        credential_id="aws_region",
        credential_key="region",
        credential_group="aws",
    ),
}
