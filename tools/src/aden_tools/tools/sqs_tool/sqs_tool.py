"""AWS SQS (Simple Queue Service) tool.

Allows agents to manage queues and exchange messages.
"""

from typing import Any, Optional

import boto3
from fastmcp import FastMCP

from aden_tools.credentials import CredentialStoreAdapter


def register_tools(mcp: FastMCP, credentials: Optional[CredentialStoreAdapter] = None):
    """Register SQS tools with the provided MCP instance."""

    def get_client():
        """Get an initialized SQS client."""
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
                "are required for SQS tools."
            )

        return boto3.client(
            "sqs",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )

    @mcp.tool()
    def sqs_create_queue(
        queue_name: str, attributes: Optional[dict[str, str]] = None
    ) -> dict[str, Any]:
        """
        Creates an SQS queue.

        Args:
            queue_name: The name of the queue.
            attributes: A dict of attributes (e.g., DelaySeconds, MaximumMessageSize).
        """
        try:
            client = get_client()
            kwargs = {"QueueName": queue_name}
            if attributes:
                kwargs["Attributes"] = attributes
            response = client.create_queue(**kwargs)
            return {"queue_url": response.get("QueueUrl"), "status": "created"}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def sqs_list_queues(queue_name_prefix: Optional[str] = None) -> dict[str, Any]:
        """Lists all SQS queue URLs."""
        try:
            client = get_client()
            kwargs = {}
            if queue_name_prefix:
                kwargs["QueueNamePrefix"] = queue_name_prefix
            response = client.list_queues(**kwargs)
            return {"queue_urls": response.get("QueueUrls", [])}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def sqs_get_queue_attributes(
        queue_url: str, attribute_names: Optional[list[str]] = None
    ) -> dict[str, Any]:
        """Retrieves metadata for an SQS queue."""
        try:
            client = get_client()
            kwargs = {
                "QueueUrl": queue_url,
                "AttributeNames": attribute_names or ["All"],
            }
            response = client.get_queue_attributes(**kwargs)
            return {"attributes": response.get("Attributes", {})}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def sqs_send_message(
        queue_url: str, message_body: str, delay_seconds: int = 0
    ) -> dict[str, Any]:
        """
        Sends a message to an SQS queue.

        Args:
            queue_url: The URL of the queue.
            message_body: The content of the message.
            delay_seconds: The duration (in seconds) to delay the message.
        """
        try:
            client = get_client()
            response = client.send_message(
                QueueUrl=queue_url, MessageBody=message_body, DelaySeconds=delay_seconds
            )
            return {"message_id": response.get("MessageId"), "status": "sent"}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def sqs_receive_messages(
        queue_url: str, max_messages: int = 1, wait_time_seconds: int = 5
    ) -> dict[str, Any]:
        """
        Receives messages from an SQS queue.

        Args:
            queue_url: The URL of the queue.
            max_messages: Maximum number of messages to retrieve (up to 10).
            wait_time_seconds: The duration for long polling (0 to 20 seconds).
        """
        try:
            client = get_client()
            response = client.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=max_messages,
                WaitTimeSeconds=wait_time_seconds,
            )
            return {"messages": response.get("Messages", [])}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def sqs_delete_message(queue_url: str, receipt_handle: str) -> dict[str, Any]:
        """Deletes a message from the queue."""
        try:
            client = get_client()
            client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
            return {"status": "deleted"}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool()
    def sqs_purge_queue(queue_url: str) -> dict[str, Any]:
        """Clears all messages from a queue."""
        try:
            client = get_client()
            client.purge_queue(QueueUrl=queue_url)
            return {"status": "purged", "queue_url": queue_url}
        except Exception as e:
            return {"error": str(e)}
