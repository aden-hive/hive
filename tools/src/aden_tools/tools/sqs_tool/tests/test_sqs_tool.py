"""Tests for AWS SQS tools."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.sqs_tool.sqs_tool import register_tools


class TestSQSTools:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        self.cred = MagicMock()
        self.cred.get.side_effect = lambda k: {
            "aws_access_key_id": "test_key",
            "aws_secret_access_key": "test_secret",
            "aws_region": "us-east-1",
        }.get(k)
        register_tools(self.mcp, credentials=self.cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("boto3.client")
    def test_sqs_create_queue(self, mock_boto):
        mock_client = MagicMock()
        mock_client.create_queue.return_value = {"QueueUrl": "https://sqs.test/queue"}
        mock_boto.return_value = mock_client

        tool = self._fn("sqs_create_queue")
        result = tool(queue_name="test_queue")

        assert result["queue_url"] == "https://sqs.test/queue"
        mock_client.create_queue.assert_called_with(QueueName="test_queue")

    @patch("boto3.client")
    def test_sqs_send_message(self, mock_boto):
        mock_client = MagicMock()
        mock_client.send_message.return_value = {"MessageId": "msg_sqs_123"}
        mock_boto.return_value = mock_client

        tool = self._fn("sqs_send_message")
        result = tool(queue_url="https://sqs.test/queue", message_body="hi")

        assert result["message_id"] == "msg_sqs_123"
        mock_client.send_message.assert_called_with(
            QueueUrl="https://sqs.test/queue", MessageBody="hi", DelaySeconds=0
        )

    @patch("boto3.client")
    def test_sqs_receive_messages(self, mock_boto):
        mock_client = MagicMock()
        messages = [{"Body": "hi", "ReceiptHandle": "rh1"}]
        mock_client.receive_message.return_value = {"Messages": messages}
        mock_boto.return_value = mock_client

        tool = self._fn("sqs_receive_messages")
        result = tool(queue_url="https://sqs.test/queue")

        assert len(result["messages"]) == 1
        assert result["messages"][0]["Body"] == "hi"
