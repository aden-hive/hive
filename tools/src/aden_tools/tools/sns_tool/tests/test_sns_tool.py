"""Tests for AWS SNS tools."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.sns_tool.sns_tool import register_tools


class TestSNSTools:
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
    def test_sns_create_topic(self, mock_boto):
        mock_client = MagicMock()
        mock_client.create_topic.return_value = {"TopicArn": "arn:aws:sns:us-east-1:123:test"}
        mock_boto.return_value = mock_client

        tool = self._fn("sns_create_topic")
        result = tool(name="test_topic")

        assert result["topic_arn"] == "arn:aws:sns:us-east-1:123:test"
        mock_client.create_topic.assert_called_with(Name="test_topic")

    @patch("boto3.client")
    def test_sns_publish_message(self, mock_boto):
        mock_client = MagicMock()
        mock_client.publish.return_value = {"MessageId": "msg_123"}
        mock_boto.return_value = mock_client

        tool = self._fn("sns_publish_message")
        result = tool(topic_arn="arn:test", message="hello")

        assert result["message_id"] == "msg_123"
        mock_client.publish.assert_called_with(TopicArn="arn:test", Message="hello")

    @patch("boto3.client")
    def test_no_credentials_error(self, mock_boto):
        self.cred.get.side_effect = lambda k: None
        tool = self._fn("sns_list_topics")
        result = tool()
        assert "error" in result
        assert "AWS credentials" in result["error"]
