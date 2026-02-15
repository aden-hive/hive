"""AWS SNS (Simple Notification Service) tool.

Allows agents to manage notification topics and publish messages.
"""

from typing import Any, Optional

import boto3
from fastmcp import FastMCP

from aden_tools.credentials import CredentialStoreAdapter


def register_tools(mcp: FastMCP, credentials: Optional[CredentialStoreAdapter] = None):
    """Register SNS tools with the provided MCP instance."""

    def get_client():
        """Get an initialized SNS client."""
        if credentials:
            access_key = credentials.get("aws_access_key_id")
            secret_key = credentials.get("aws_secret_access_key")
            region = credentials.get("aws_region")
        else:
            import os
            access_key = os.environ.get("AWS_ACCESS_KEY_ID")
            secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
            region = os.environ.get("AWS_REGION")

        if not access_key or not secret_key or not region:
            raise ValueError(
                "AWS credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION) "
                "are required for SNS tools."
            )

        return boto3.client(
            "sns",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )

    @mcp.tool()
    def sns_create_topic(name: str, attributes: Optional[dict[str, str]] = None) -> dict[str, Any]:
        """
        Creates an SNS topic.

        Args:
            name: The name of the topic to create.
            attributes: A dict of attributes to set on the topic (e.g. DisplayName).
        """
        try:
            client = get_client()
            kwargs = {"Name": name}
            if attributes:
                kwargs["Attributes"] = attributes
            response = client.create_topic(**kwargs)
            return {"topic_arn": response.get("TopicArn"), "status": "created"}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def sns_list_topics() -> dict[str, Any]:
        """Lists all SNS topic ARNs."""
        try:
            client = get_client()
            response = client.list_topics()
            return {"topics": [t["TopicArn"] for t in response.get("Topics", [])]}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def sns_delete_topic(topic_arn: str) -> dict[str, Any]:
        """Deletes an SNS topic."""
        try:
            client = get_client()
            client.delete_topic(TopicArn=topic_arn)
            return {"status": "deleted", "topic_arn": topic_arn}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def sns_publish_message(
        topic_arn: str,
        message: str,
        subject: Optional[str] = None,
        phone_number: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        Publishes a message to an SNS topic or phone number.

        Args:
            topic_arn: The ARN of the topic to publish to.
            message: The message body to send.
            subject: Optional subject for the message (useful for email).
            phone_number: Optional phone number to send message to directly (SMS).
        """
        try:
            client = get_client()
            kwargs = {"Message": message}
            if topic_arn:
                kwargs["TopicArn"] = topic_arn
            elif phone_number:
                kwargs["PhoneNumber"] = phone_number
            else:
                return {"error": "Either topic_arn or phone_number must be provided."}

            if subject:
                kwargs["Subject"] = subject

            response = client.publish(**kwargs)
            return {"message_id": response.get("MessageId"), "status": "sent"}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def sns_list_subscriptions_by_topic(topic_arn: str) -> dict[str, Any]:
        """Lists subscriptions for a specific topic."""
        try:
            client = get_client()
            response = client.list_subscriptions_by_topic(TopicArn=topic_arn)
            return {"subscriptions": response.get("Subscriptions", [])}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def sns_subscribe_endpoint(
        topic_arn: str, protocol: str, endpoint: str
    ) -> dict[str, Any]:
        """
        Subscribes an endpoint to a topic.

        Args:
            topic_arn: The ARN of the topic to subscribe to.
            protocol: The protocol to use (e.g., 'email', 'sms', 'lambda', 'sqs').
            endpoint: The endpoint that receives notifications (e.g., email address, phone number).
        """
        try:
            client = get_client()
            response = client.subscribe(
                TopicArn=topic_arn, Protocol=protocol, Endpoint=endpoint
            )
            return {
                "subscription_arn": response.get("SubscriptionArn"),
                "status": "subscription_initiated",
            }
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def sns_unsubscribe(subscription_arn: str) -> dict[str, Any]:
        """Removes a subscription from a topic."""
        try:
            client = get_client()
            client.unsubscribe(SubscriptionArn=subscription_arn)
            return {"status": "unsubscribed", "subscription_arn": subscription_arn}
        except Exception as e:
            return {"error": str(e)}
