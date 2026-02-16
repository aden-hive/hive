"""AWS CloudWatch tool implementation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import boto3
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from aden_tools.credentials import CredentialStoreAdapter

logger = logging.getLogger(__name__)


def get_cloudwatch_client(credentials: CredentialStoreAdapter | None = None):
    """
    Initialize a CloudWatch client using available credentials.
    """
    import os
    aws_access_key = os.environ.get("AWS_ACCESS_KEY_ID")
    aws_secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
    aws_region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"

    if credentials:
        # Try to get from adapter if available
        key = credentials.get("aws_cloudwatch")
        if key:
            aws_access_key = key
            # If the adapter is a store adapter, we can try to get the secret too
            # but for now we assume it's in env if possible or just use what we have
            try:
                secret = credentials.get_key("aws_cloudwatch", "aws_secret_access_key")
                if secret:
                    aws_secret_key = secret
                region = credentials.get_key("aws_cloudwatch", "aws_region")
                if region:
                    aws_region = region
            except (AttributeError, KeyError):
                pass

    return boto3.client(
        "cloudwatch",
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key,
        region_name=aws_region,
    )


def get_logs_client(credentials: CredentialStoreAdapter | None = None):
    """
    Initialize a CloudWatch Logs client using available credentials.
    """
    import os
    aws_access_key = os.environ.get("AWS_ACCESS_KEY_ID")
    aws_secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
    aws_region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"

    if credentials:
        key = credentials.get("aws_cloudwatch")
        if key:
            aws_access_key = key
            try:
                secret = credentials.get_key("aws_cloudwatch", "aws_secret_access_key")
                if secret:
                    aws_secret_key = secret
                region = credentials.get_key("aws_cloudwatch", "aws_region")
                if region:
                    aws_region = region
            except (AttributeError, KeyError):
                pass

    return boto3.client(
        "logs",
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key,
        region_name=aws_region,
    )


def register_tools(mcp: FastMCP, credentials: CredentialStoreAdapter | None = None) -> None:
    """
    Register CloudWatch tools with the FastMCP server.
    
    Args:
        mcp: FastMCP server instance
        credentials: Optional CredentialStoreAdapter instance
    """

    @mcp.tool()
    async def cloudwatch_put_metric(
        namespace: str,
        metric_name: str,
        value: float,
        unit: str = "None",
        dimensions: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Publish a custom metric data point to CloudWatch.
        
        Args:
            namespace: The namespace for the metric data.
            metric_name: The name of the metric.
            value: The value for the metric.
            unit: The unit of the metric (e.g., Seconds, Bytes, Count, Percent).
            dimensions: Optional dictionary of dimensions (key-value pairs) for the metric.
        """
        try:
            client = get_cloudwatch_client(credentials)
            
            metric_data = {
                "MetricName": metric_name,
                "Value": value,
                "Unit": unit,
            }
            
            if dimensions:
                metric_data["Dimensions"] = [
                    {"Name": k, "Value": v} for k, v in dimensions.items()
                ]
                
            client.put_metric_data(
                Namespace=namespace,
                MetricData=[metric_data]
            )
            
            return {
                "status": "success",
                "message": f"Successfully published metric {metric_name} to namespace {namespace}",
            }
        except ClientError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            return {"status": "error", "message": f"An unexpected error occurred: {e!s}"}

    @mcp.tool()
    async def cloudwatch_put_log_event(
        log_group: str,
        log_stream: str,
        message: str,
    ) -> Dict[str, Any]:
        """
        Send a log event to a CloudWatch Log Group/Stream.
        Auto-creates the log group and stream if they don't exist.
        
        Args:
            log_group: The name of the log group.
            log_stream: The name of the log stream.
            message: The log message to send.
        """
        try:
            client = get_logs_client(credentials)
            
            # Ensure log group exists
            try:
                client.create_log_group(logGroupName=log_group)
            except client.exceptions.ResourceAlreadyExistsException:
                pass
                
            # Ensure log stream exists
            try:
                client.create_log_stream(logGroupName=log_group, logStreamName=log_stream)
            except client.exceptions.ResourceAlreadyExistsException:
                pass
                
            # Put log event
            # Note: For V1 we're not handling sequence tokens for simplicity as Boto3 handles it
            # or it might not be required for newer log streams. 
            import time
            client.put_log_events(
                logGroupName=log_group,
                logStreamName=log_stream,
                logEvents=[
                    {
                        "timestamp": int(time.time() * 1000),
                        "message": message
                    }
                ]
            )
            
            return {
                "status": "success",
                "message": f"Successfully sent log event to {log_group}/{log_stream}",
            }
        except ClientError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            return {"status": "error", "message": f"An unexpected error occurred: {e!s}"}

    @mcp.tool()
    async def cloudwatch_create_alarm(
        alarm_name: str,
        namespace: str,
        metric_name: str,
        threshold: float,
        comparison_operator: str = "GreaterThanThreshold",
        evaluation_periods: int = 1,
        period: int = 300,
        statistic: str = "Average",
        alarm_actions: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Create or update a CloudWatch Alarm.
        
        Args:
            alarm_name: The name for the alarm.
            namespace: The namespace for the metric associated with the alarm.
            metric_name: The name for the metric associated with the alarm.
            threshold: The value against which the specified statistic is compared.
            comparison_operator: The arithmetic operation to use when comparing the specified statistic and threshold.
            evaluation_periods: The number of periods over which data is compared to the specified threshold.
            period: The length, in seconds, used each time the metric specified in metric_name is evaluated.
            statistic: The statistic for the metric specified in metric_name, other than percentile.
            alarm_actions: The actions to execute when this alarm transitions to an ALARM state from any other state.
        """
        try:
            client = get_cloudwatch_client(credentials)
            
            params = {
                "AlarmName": alarm_name,
                "ComparisonOperator": comparison_operator,
                "EvaluationPeriods": evaluation_periods,
                "MetricName": metric_name,
                "Namespace": namespace,
                "Period": period,
                "Statistic": statistic,
                "Threshold": threshold,
            }
            
            if alarm_actions:
                params["AlarmActions"] = alarm_actions
                
            client.put_metric_alarm(**params)
            
            return {
                "status": "success",
                "message": f"Successfully created/updated alarm {alarm_name}",
            }
        except ClientError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            return {"status": "error", "message": f"An unexpected error occurred: {e!s}"}

    @mcp.tool()
    async def cloudwatch_get_metric_stats(
        namespace: str,
        metric_name: str,
        start_time: str,
        end_time: str,
        period: int = 300,
        statistics: List[str] = None,
        dimensions: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Retrieve metric statistics from CloudWatch.
        
        Args:
            namespace: The namespace of the metric.
            metric_name: The name of the metric.
            start_time: The time stamp that determines the first data point to return (ISO 8601).
            end_time: The time stamp that determines the last data point to return (ISO 8601).
            period: The granularity, in seconds, of the returned data points.
            statistics: The metric statistics to return. Defaults to ["Average"].
            dimensions: Optional dictionary of dimensions.
        """
        if statistics is None:
            statistics = ["Average"]
            
        try:
            client = get_cloudwatch_client(credentials)
            from datetime import datetime
            
            # Helper to parse ISO format
            def parse_time(t_str):
                try:
                    return datetime.fromisoformat(t_str.replace("Z", "+00:00"))
                except ValueError:
                    return datetime.strptime(t_str, "%Y-%m-%dT%H:%M:%S")

            params = {
                "Namespace": namespace,
                "MetricName": metric_name,
                "StartTime": parse_time(start_time),
                "EndTime": parse_time(end_time),
                "Period": period,
                "Statistics": statistics,
            }
            
            if dimensions:
                params["Dimensions"] = [
                    {"Name": k, "Value": v} for k, v in dimensions.items()
                ]
                
            response = client.get_metric_statistics(**params)
            
            # Convert datetimes to strings for JSON serialization
            datapoints = response.get("Datapoints", [])
            for dp in datapoints:
                if "Timestamp" in dp:
                    dp["Timestamp"] = dp["Timestamp"].isoformat()
                    
            return {
                "status": "success",
                "datapoints": datapoints,
                "label": response.get("Label"),
            }
        except ClientError as e:
            return {"status": "error", "message": str(e)}
        except Exception as e:
            return {"status": "error", "message": f"An unexpected error occurred: {e!s}"}
