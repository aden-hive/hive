"""AWS CloudWatch integration.

Provides metrics, alarms, and log insights via the CloudWatch REST API
with SigV4 signing. No third-party AWS SDK required.

Requires:
    AWS_ACCESS_KEY_ID
    AWS_SECRET_ACCESS_KEY
    AWS_REGION  (defaults to us-east-1)
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import os
import urllib.parse
from typing import Any

import httpx
from fastmcp import FastMCP


# ---------------------------------------------------------------------------
# SigV4 helpers (shared pattern with aws_s3_tool)
# ---------------------------------------------------------------------------

def _get_config() -> tuple[str, str, str] | dict:
    """Return (access_key, secret_key, region) or an error dict."""
    access_key = os.getenv("AWS_ACCESS_KEY_ID", "")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    region = os.getenv("AWS_REGION", "us-east-1")
    if not access_key or not secret_key:
        return {
            "error": "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are required",
            "help": (
                "Set AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and optionally "
                "AWS_REGION environment variables."
            ),
        }
    return access_key, secret_key, region


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret_key: str, datestamp: str, region: str, service: str) -> bytes:
    k_date = _sign(("AWS4" + secret_key).encode("utf-8"), datestamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    return _sign(k_service, "aws4_request")


def _signed_headers(
    method: str,
    host: str,
    path: str,
    query_params: dict[str, str],
    payload: str,
    access_key: str,
    secret_key: str,
    region: str,
    service: str,
) -> dict[str, str]:
    """Build SigV4-signed headers for an AWS API request."""
    now = datetime.datetime.utcnow()
    amzdate = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")

    canonical_querystring = urllib.parse.urlencode(
        sorted(query_params.items()), quote_via=urllib.parse.quote
    )
    payload_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    canonical_headers = f"host:{host}\nx-amz-date:{amzdate}\n"
    signed_headers_str = "host;x-amz-date"

    canonical_request = "\n".join([
        method,
        path,
        canonical_querystring,
        canonical_headers,
        signed_headers_str,
        payload_hash,
    ])

    credential_scope = f"{datestamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amzdate,
        credential_scope,
        hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
    ])

    signing_key = _signing_key(secret_key, datestamp, region, service)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers_str}, Signature={signature}"
    )
    return {
        "x-amz-date": amzdate,
        "Authorization": authorization,
        "Content-Type": "application/x-www-form-urlencoded",
    }


def _cw_post(
    access_key: str,
    secret_key: str,
    region: str,
    params: dict[str, str],
) -> dict[str, Any]:
    """POST a CloudWatch request and return the parsed JSON response."""
    host = f"monitoring.{region}.amazonaws.com"
    url = f"https://{host}/"
    payload = urllib.parse.urlencode(params)
    headers = _signed_headers(
        method="POST",
        host=host,
        path="/",
        query_params={},
        payload=payload,
        access_key=access_key,
        secret_key=secret_key,
        region=region,
        service="monitoring",
    )
    headers["Content-Type"] = "application/x-www-form-urlencoded"
    try:
        resp = httpx.post(url, content=payload.encode("utf-8"), headers=headers, timeout=30)
        resp.raise_for_status()
        return {"raw_xml": resp.text}
    except httpx.HTTPStatusError as exc:
        return {"error": f"HTTP {exc.response.status_code}", "body": exc.response.text}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def _logs_post(
    access_key: str,
    secret_key: str,
    region: str,
    target: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """POST a CloudWatch Logs request and return parsed JSON."""
    host = f"logs.{region}.amazonaws.com"
    url = f"https://{host}/"
    payload_str = json.dumps(body)
    headers = _signed_headers(
        method="POST",
        host=host,
        path="/",
        query_params={},
        payload=payload_str,
        access_key=access_key,
        secret_key=secret_key,
        region=region,
        service="logs",
    )
    headers["Content-Type"] = "application/x-amz-json-1.1"
    headers["X-Amz-Target"] = target
    try:
        resp = httpx.post(
            url,
            content=payload_str.encode("utf-8"),
            headers=headers,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as exc:
        return {"error": f"HTTP {exc.response.status_code}", "body": exc.response.text}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register_tools(mcp: FastMCP, credentials=None) -> None:  # noqa: ANN001
    """Register AWS CloudWatch tools with a FastMCP server."""

    @mcp.tool(name="cloudwatch_list_metrics")
    def cloudwatch_list_metrics(
        namespace: str = "",
        metric_name: str = "",
        dimensions: str = "",
    ) -> dict[str, Any]:
        """List available CloudWatch metrics.

        Args:
            namespace: Optional AWS namespace filter, e.g. ``AWS/EC2``.
            metric_name: Optional metric name filter, e.g. ``CPUUtilization``.
            dimensions: Optional comma-separated ``Name=Value`` dimension filters,
                e.g. ``InstanceId=i-1234567890abcdef0``.

        Returns:
            Dict with ``metrics`` list (each entry has ``Namespace``, ``MetricName``,
            ``Dimensions``) or ``error`` on failure.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        access_key, secret_key, region = cfg

        params: dict[str, str] = {
            "Action": "ListMetrics",
            "Version": "2010-08-01",
        }
        if namespace:
            params["Namespace"] = namespace
        if metric_name:
            params["MetricName"] = metric_name
        # Parse dimensions: "InstanceId=i-xxx,AutoScalingGroupName=asg-yyy"
        if dimensions:
            for idx, pair in enumerate(dimensions.split(","), start=1):
                pair = pair.strip()
                if "=" in pair:
                    name, value = pair.split("=", 1)
                    params[f"Dimensions.member.{idx}.Name"] = name.strip()
                    params[f"Dimensions.member.{idx}.Value"] = value.strip()

        result = _cw_post(access_key, secret_key, region, params)
        if "error" in result:
            return result
        # Return raw XML — agents can parse it; keep tool thin
        return {"region": region, "response": result["raw_xml"]}

    @mcp.tool(name="cloudwatch_get_metric_statistics")
    def cloudwatch_get_metric_statistics(
        namespace: str,
        metric_name: str,
        start_time: str,
        end_time: str,
        period: int = 300,
        statistics: str = "Average",
        dimensions: str = "",
    ) -> dict[str, Any]:
        """Retrieve statistics for a CloudWatch metric over a time range.

        Args:
            namespace: AWS namespace, e.g. ``AWS/EC2``.
            metric_name: Metric name, e.g. ``CPUUtilization``.
            start_time: ISO-8601 UTC start, e.g. ``2024-01-01T00:00:00Z``.
            end_time: ISO-8601 UTC end, e.g. ``2024-01-01T01:00:00Z``.
            period: Granularity in seconds (min 60). Default 300.
            statistics: Comma-separated stats to retrieve. Choices:
                ``Average``, ``Sum``, ``Minimum``, ``Maximum``, ``SampleCount``.
                Default ``Average``.
            dimensions: Optional comma-separated ``Name=Value`` pairs,
                e.g. ``InstanceId=i-1234567890abcdef0``.

        Returns:
            Dict with ``datapoints`` list or ``error`` on failure.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        access_key, secret_key, region = cfg

        params: dict[str, str] = {
            "Action": "GetMetricStatistics",
            "Version": "2010-08-01",
            "Namespace": namespace,
            "MetricName": metric_name,
            "StartTime": start_time,
            "EndTime": end_time,
            "Period": str(period),
        }
        for idx, stat in enumerate(statistics.split(","), start=1):
            params[f"Statistics.member.{idx}"] = stat.strip()

        if dimensions:
            for idx, pair in enumerate(dimensions.split(","), start=1):
                pair = pair.strip()
                if "=" in pair:
                    name, value = pair.split("=", 1)
                    params[f"Dimensions.member.{idx}.Name"] = name.strip()
                    params[f"Dimensions.member.{idx}.Value"] = value.strip()

        result = _cw_post(access_key, secret_key, region, params)
        if "error" in result:
            return result
        return {
            "namespace": namespace,
            "metric_name": metric_name,
            "period": period,
            "region": region,
            "response": result["raw_xml"],
        }

    @mcp.tool(name="cloudwatch_describe_alarms")
    def cloudwatch_describe_alarms(
        alarm_names: str = "",
        alarm_name_prefix: str = "",
        state_value: str = "",
        max_records: int = 50,
    ) -> dict[str, Any]:
        """List CloudWatch alarms and their current state.

        Args:
            alarm_names: Optional comma-separated alarm names to filter.
            alarm_name_prefix: Optional prefix to filter alarm names.
            state_value: Optional state filter: ``OK``, ``ALARM``, or
                ``INSUFFICIENT_DATA``.
            max_records: Maximum number of alarms to return (1–100). Default 50.

        Returns:
            Dict with ``response`` (raw XML) or ``error`` on failure.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        access_key, secret_key, region = cfg

        params: dict[str, str] = {
            "Action": "DescribeAlarms",
            "Version": "2010-08-01",
            "MaxRecords": str(min(max(1, max_records), 100)),
        }
        if state_value:
            params["StateValue"] = state_value
        if alarm_name_prefix:
            params["AlarmNamePrefix"] = alarm_name_prefix
        if alarm_names:
            for idx, name in enumerate(alarm_names.split(","), start=1):
                params[f"AlarmNames.member.{idx}"] = name.strip()

        result = _cw_post(access_key, secret_key, region, params)
        if "error" in result:
            return result
        return {"region": region, "response": result["raw_xml"]}

    @mcp.tool(name="cloudwatch_logs_start_query")
    def cloudwatch_logs_start_query(
        log_group_names: str,
        query_string: str,
        start_time: int,
        end_time: int,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Start a CloudWatch Logs Insights query.

        Args:
            log_group_names: Comma-separated log group names to query.
            query_string: CloudWatch Logs Insights query, e.g.
                ``fields @timestamp, @message | sort @timestamp desc``.
            start_time: Query start as Unix epoch seconds.
            end_time: Query end as Unix epoch seconds.
            limit: Maximum number of log events to return (1–10000). Default 100.

        Returns:
            Dict with ``queryId`` to pass to ``cloudwatch_logs_get_query_results``,
            or ``error`` on failure.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        access_key, secret_key, region = cfg

        body: dict[str, Any] = {
            "logGroupNames": [n.strip() for n in log_group_names.split(",")],
            "queryString": query_string,
            "startTime": start_time,
            "endTime": end_time,
            "limit": min(max(1, limit), 10000),
        }
        result = _logs_post(
            access_key, secret_key, region,
            target="Logs_20140328.StartQuery",
            body=body,
        )
        if "error" in result:
            return result
        return {"queryId": result.get("queryId"), "region": region}

    @mcp.tool(name="cloudwatch_logs_get_query_results")
    def cloudwatch_logs_get_query_results(query_id: str) -> dict[str, Any]:
        """Retrieve the results of a CloudWatch Logs Insights query.

        Call this after ``cloudwatch_logs_start_query``. Poll until ``status``
        is ``Complete`` or ``Failed``.

        Args:
            query_id: The query ID returned by ``cloudwatch_logs_start_query``.

        Returns:
            Dict with ``status`` (``Scheduled``, ``Running``, ``Complete``,
            ``Failed``, or ``Cancelled``), ``results`` list of log event rows,
            and ``statistics`` dict, or ``error`` on failure.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        access_key, secret_key, region = cfg

        result = _logs_post(
            access_key, secret_key, region,
            target="Logs_20140328.GetQueryResults",
            body={"queryId": query_id},
        )
        if "error" in result:
            return result
        return {
            "status": result.get("status"),
            "results": result.get("results", []),
            "statistics": result.get("statistics", {}),
            "region": region,
        }

    @mcp.tool(name="cloudwatch_logs_describe_log_groups")
    def cloudwatch_logs_describe_log_groups(
        log_group_name_prefix: str = "",
        limit: int = 50,
    ) -> dict[str, Any]:
        """List CloudWatch log groups.

        Args:
            log_group_name_prefix: Optional prefix filter for log group names.
            limit: Maximum number of log groups to return (1–50). Default 50.

        Returns:
            Dict with ``logGroups`` list (each entry has ``logGroupName``,
            ``storedBytes``, ``retentionInDays``) or ``error`` on failure.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        access_key, secret_key, region = cfg

        body: dict[str, Any] = {"limit": min(max(1, limit), 50)}
        if log_group_name_prefix:
            body["logGroupNamePrefix"] = log_group_name_prefix

        result = _logs_post(
            access_key, secret_key, region,
            target="Logs_20140328.DescribeLogGroups",
            body=body,
        )
        if "error" in result:
            return result
        return {
            "logGroups": result.get("logGroups", []),
            "nextToken": result.get("nextToken"),
            "region": region,
        }
