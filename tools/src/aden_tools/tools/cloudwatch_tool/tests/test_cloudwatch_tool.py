"""Unit tests for AWS CloudWatch tools."""

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

import boto3
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from aden_tools.tools.cloudwatch_tool.cloudwatch_tool import (
    register_tools,
)


class TestCloudWatchTool(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.mcp = MagicMock()
        self.credentials = MagicMock()
        self.credentials.get.side_effect = lambda name: {
            "aws_cloudwatch": "test-key",
        }.get(name)
        self.credentials.get_key.side_effect = lambda name, key: {
            ("aws_cloudwatch", "aws_secret_access_key"): "test-secret",
            ("aws_cloudwatch", "aws_region"): "us-east-1",
        }.get((name, key))

        # Register tools to capture the decorated functions
        register_tools(self.mcp, self.credentials)
        
        # The decorator mock is self.mcp.tool.return_value
        # It was called for each function
        decorator = self.mcp.tool.return_value
        self.put_metric = decorator.call_args_list[0][0][0]
        self.put_log = decorator.call_args_list[1][0][0]
        self.create_alarm = decorator.call_args_list[2][0][0]
        self.get_stats = decorator.call_args_list[3][0][0]

        # Real clients for stubbing
        self.cw_client = boto3.client("cloudwatch", region_name="us-east-1")
        self.logs_client = boto3.client("logs", region_name="us-east-1")

    @patch("aden_tools.tools.cloudwatch_tool.cloudwatch_tool.get_cloudwatch_client")
    async def test_cloudwatch_put_metric_success(self, mock_get_client):
        mock_get_client.return_value = self.cw_client
        with Stubber(self.cw_client) as stubber:
            expected_params = {
                "Namespace": "TestNS",
                "MetricData": [
                    {
                        "MetricName": "TestMetric",
                        "Value": 1.0,
                        "Unit": "Count",
                        "Dimensions": [{"Name": "Agent", "Value": "TestAgent"}]
                    }
                ]
            }
            stubber.add_response("put_metric_data", {}, expected_params)
            
            result = await self.put_metric(
                namespace="TestNS",
                metric_name="TestMetric",
                value=1.0,
                unit="Count",
                dimensions={"Agent": "TestAgent"}
            )

            self.assertEqual(result["status"], "success")
            stubber.assert_no_pending_responses()

    @patch("aden_tools.tools.cloudwatch_tool.cloudwatch_tool.get_logs_client")
    async def test_cloudwatch_put_log_event_success(self, mock_get_client):
        mock_get_client.return_value = self.logs_client
        with Stubber(self.logs_client) as stubber:
            # Responses for create_log_group and create_log_stream
            stubber.add_response("create_log_group", {}, {"logGroupName": "TestGroup"})
            stubber.add_response("create_log_stream", {}, {"logGroupName": "TestGroup", "logStreamName": "TestStream"})
            
            # Response for put_log_events
            stubber.add_response("put_log_events", {"nextSequenceToken": "token"}, {
                "logGroupName": "TestGroup",
                "logStreamName": "TestStream",
                "logEvents": [{"timestamp": unittest.mock.ANY, "message": "Test Message"}]
            })
            
            result = await self.put_log(
                log_group="TestGroup",
                log_stream="TestStream",
                message="Test Message"
            )

            self.assertEqual(result["status"], "success")
            stubber.assert_no_pending_responses()

    @patch("aden_tools.tools.cloudwatch_tool.cloudwatch_tool.get_cloudwatch_client")
    async def test_cloudwatch_create_alarm_success(self, mock_get_client):
        mock_get_client.return_value = self.cw_client
        with Stubber(self.cw_client) as stubber:
            expected_params = {
                "AlarmName": "TestAlarm",
                "ComparisonOperator": "GreaterThanThreshold",
                "EvaluationPeriods": 1,
                "MetricName": "TestMetric",
                "Namespace": "TestNS",
                "Period": 300,
                "Statistic": "Average",
                "Threshold": 10.0,
                "AlarmActions": ["arn:aws:sns:test"]
            }
            stubber.add_response("put_metric_alarm", {}, expected_params)

            result = await self.create_alarm(
                alarm_name="TestAlarm",
                namespace="TestNS",
                metric_name="TestMetric",
                threshold=10.0,
                alarm_actions=["arn:aws:sns:test"]
            )

            self.assertEqual(result["status"], "success")
            stubber.assert_no_pending_responses()

    @patch("aden_tools.tools.cloudwatch_tool.cloudwatch_tool.get_cloudwatch_client")
    async def test_cloudwatch_get_metric_stats_success(self, mock_get_client):
        mock_get_client.return_value = self.cw_client
        with Stubber(self.cw_client) as stubber:
            start_time = "2024-01-01T00:00:00Z"
            end_time = "2024-01-01T01:00:00Z"
            
            # Use UTC timezone for comparison
            dt = datetime.fromisoformat("2024-01-01T00:05:00+00:00")
            
            response = {
                "Label": "TestLabel",
                "Datapoints": [
                    {
                        "Timestamp": dt,
                        "Average": 5.0,
                        "Unit": "Count"
                    }
                ]
            }
            
            stubber.add_response("get_metric_statistics", response, {
                "Namespace": "TestNS",
                "MetricName": "TestMetric",
                "StartTime": datetime.fromisoformat("2024-01-01T00:00:00+00:00"),
                "EndTime": datetime.fromisoformat("2024-01-01T01:00:00+00:00"),
                "Period": 300,
                "Statistics": ["Average"]
            })

            result = await self.get_stats(
                namespace="TestNS",
                metric_name="TestMetric",
                start_time=start_time,
                end_time=end_time
            )

            self.assertEqual(result["status"], "success")
            self.assertEqual(len(result["datapoints"]), 1)
            self.assertEqual(result["datapoints"][0]["Average"], 5.0)
            stubber.assert_no_pending_responses()

    @patch("aden_tools.tools.cloudwatch_tool.cloudwatch_tool.get_cloudwatch_client")
    async def test_client_error_handling(self, mock_get_client):
        mock_get_client.return_value = self.cw_client
        with Stubber(self.cw_client) as stubber:
            stubber.add_client_error("put_metric_data", "AccessDenied", "User is not authorized")

            result = await self.put_metric(
                namespace="Test",
                metric_name="Test",
                value=1.0
            )

            self.assertEqual(result["status"], "error")
            self.assertIn("AccessDenied", result["message"])


if __name__ == "__main__":
    unittest.main()
