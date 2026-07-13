"""AWS CloudWatch integration.

Provides observability operations over the CloudWatch Query API (metrics and
alarms) and the CloudWatch Logs Insights JSON API, signed with AWS SigV4.

This mirrors the existing ``aws_s3_tool`` convention: requests are signed by hand
with ``httpx`` rather than pulling in ``boto3``, so the tool adds no new
dependency. Requires AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_REGION.

Tools:
- cloudwatch_list_metrics          — discover metrics in a namespace
- cloudwatch_get_metric_statistics — fetch datapoints for a metric
- cloudwatch_list_alarms           — list alarms filtered by state
- cloudwatch_start_logs_query      — start a Logs Insights query
- cloudwatch_get_query_results     — poll results for a running query
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import os
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any

import httpx
from fastmcp import FastMCP

# CloudWatch (monitoring) Query API version.
CW_API_VERSION = "2010-08-01"
# CloudWatch Logs JSON API target prefix (X-Amz-Target: Logs_20140328.<Action>).
LOGS_TARGET_PREFIX = "Logs_20140328"


def _get_config() -> tuple[str, str, str] | dict:
    """Return (access_key, secret_key, region) or an error dict."""
    access_key = os.getenv("AWS_ACCESS_KEY_ID", "")
    secret_key = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    region = os.getenv("AWS_REGION", "us-east-1")
    if not access_key or not secret_key:
        return {
            "error": "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are required",
            "help": "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables",
        }
    return access_key, secret_key, region


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret_key: str, datestamp: str, region: str, service: str) -> bytes:
    k_date = _sign(("AWS4" + secret_key).encode("utf-8"), datestamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    return _sign(k_service, "aws4_request")


def _sigv4_headers(
    method: str,
    service: str,
    host: str,
    region: str,
    access_key: str,
    secret_key: str,
    query_params: dict,
    body: bytes,
    extra_headers: dict | None = None,
) -> dict:
    """Build SigV4-signed headers for an AWS request.

    Generic over ``service`` (e.g. "monitoring" or "logs") so both the
    CloudWatch Query API and the Logs JSON API can share one signer.
    """
    now = datetime.datetime.now(datetime.UTC)
    datestamp = now.strftime("%Y%m%d")
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    payload_hash = hashlib.sha256(body).hexdigest()

    headers = {k.lower(): v for k, v in (extra_headers or {}).items()}
    headers["host"] = host
    headers["x-amz-date"] = amz_date
    headers["x-amz-content-sha256"] = payload_hash

    # Canonical query string (sorted, percent-encoded).
    canonical_qs = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(str(v), safe='')}"
        for k, v in sorted(query_params.items())
    )

    signed_header_names = sorted(headers.keys())
    canonical_headers = "".join(f"{k}:{headers[k].strip()}\n" for k in signed_header_names)
    signed_headers = ";".join(signed_header_names)

    canonical_request = f"{method}\n/\n{canonical_qs}\n{canonical_headers}\n{signed_headers}\n{payload_hash}"

    scope = f"{datestamp}/{region}/{service}/aws4_request"
    string_to_sign = f"AWS4-HMAC-SHA256\n{amz_date}\n{scope}\n{hashlib.sha256(canonical_request.encode()).hexdigest()}"
    signature = hmac.new(
        _signing_key(secret_key, datestamp, region, service),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    headers["Authorization"] = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope},SignedHeaders={signed_headers},Signature={signature}"
    )
    return headers


def _strip_ns(root: ET.Element) -> ET.Element:
    """Remove XML namespaces so ``find``/``findall`` can use bare tags."""
    for elem in root.iter():
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]
    return root


def _cw_query(action: str, params: dict, cfg: tuple[str, str, str]) -> dict | ET.Element:
    """Call the CloudWatch (monitoring) Query API. Returns parsed XML or an error dict."""
    access_key, secret_key, region = cfg
    host = f"monitoring.{region}.amazonaws.com"
    query = {"Action": action, "Version": CW_API_VERSION, **params}

    headers = _sigv4_headers("GET", "monitoring", host, region, access_key, secret_key, query, b"")
    try:
        resp = httpx.get(f"https://{host}/", headers=headers, params=query, timeout=30)
    except httpx.HTTPError as exc:
        return {"error": f"CloudWatch request failed: {exc}"}
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return _strip_ns(ET.fromstring(resp.text))


def _logs_json(action: str, payload: dict, cfg: tuple[str, str, str]) -> dict:
    """Call the CloudWatch Logs JSON API. Returns the decoded JSON or an error dict."""
    access_key, secret_key, region = cfg
    host = f"logs.{region}.amazonaws.com"
    body = json.dumps(payload).encode("utf-8")
    extra = {
        "content-type": "application/x-amz-json-1.1",
        "x-amz-target": f"{LOGS_TARGET_PREFIX}.{action}",
    }
    headers = _sigv4_headers("POST", "logs", host, region, access_key, secret_key, {}, body, extra)
    try:
        resp = httpx.post(f"https://{host}/", headers=headers, content=body, timeout=30)
    except httpx.HTTPError as exc:
        return {"error": f"CloudWatch Logs request failed: {exc}"}
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:500]}"}
    return resp.json()


def _dimension_params(name: str, value: str) -> dict:
    """Build the CloudWatch ``Dimensions.member.1`` query params for one dimension."""
    if not name or not value:
        return {}
    return {"Dimensions.member.1.Name": name, "Dimensions.member.1.Value": value}


def register_tools(mcp: FastMCP, credentials: Any = None) -> None:
    """Register AWS CloudWatch tools."""

    @mcp.tool()
    def cloudwatch_list_metrics(
        namespace: str,
        metric_name: str = "",
        dimension_name: str = "",
        dimension_value: str = "",
    ) -> dict:
        """Discover available metrics for a namespace.

        Args:
            namespace: Metric namespace (e.g. 'AWS/EC2').
            metric_name: Optional exact metric name filter (e.g. 'CPUUtilization').
            dimension_name: Optional dimension name to filter by (e.g. 'InstanceId').
            dimension_value: Value for dimension_name (e.g. 'i-1234567890abcdef0').
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        if not namespace:
            return {"error": "namespace is required"}

        params: dict[str, Any] = {"Namespace": namespace}
        if metric_name:
            params["MetricName"] = metric_name
        params.update(_dimension_params(dimension_name, dimension_value))

        root = _cw_query("ListMetrics", params, cfg)
        if isinstance(root, dict):
            return root

        metrics = []
        for m in root.findall(".//Metrics/member"):
            dims = []
            for d in m.findall(".//Dimensions/member"):
                dn, dv = d.find("Name"), d.find("Value")
                dims.append({"name": dn.text if dn is not None else None, "value": dv.text if dv is not None else None})
            name_el = m.find("MetricName")
            ns_el = m.find("Namespace")
            metrics.append(
                {
                    "namespace": ns_el.text if ns_el is not None else None,
                    "metric_name": name_el.text if name_el is not None else None,
                    "dimensions": dims,
                }
            )
        return {"count": len(metrics), "metrics": metrics}

    @mcp.tool()
    def cloudwatch_get_metric_statistics(
        namespace: str,
        metric_name: str,
        start_time: str,
        end_time: str,
        period: int = 300,
        statistics: str = "Average",
        dimension_name: str = "",
        dimension_value: str = "",
    ) -> dict:
        """Fetch datapoints for a metric over a time range.

        Args:
            namespace: Metric namespace (e.g. 'AWS/EC2').
            metric_name: Metric name (e.g. 'CPUUtilization').
            start_time: ISO 8601 UTC start (e.g. '2026-07-13T00:00:00Z').
            end_time: ISO 8601 UTC end (e.g. '2026-07-13T01:00:00Z').
            period: Granularity in seconds, multiple of 60 (default 300).
            statistics: Comma-separated stats: Average, Sum, Minimum, Maximum, SampleCount.
            dimension_name: Optional dimension name (e.g. 'InstanceId').
            dimension_value: Value for dimension_name.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        if not namespace or not metric_name:
            return {"error": "namespace and metric_name are required"}
        if not start_time or not end_time:
            return {"error": "start_time and end_time are required (ISO 8601, e.g. 2026-07-13T00:00:00Z)"}

        params: dict[str, Any] = {
            "Namespace": namespace,
            "MetricName": metric_name,
            "StartTime": start_time,
            "EndTime": end_time,
            "Period": str(max(60, period)),
        }
        for i, stat in enumerate((s.strip() for s in statistics.split(",") if s.strip()), start=1):
            params[f"Statistics.member.{i}"] = stat
        params.update(_dimension_params(dimension_name, dimension_value))

        root = _cw_query("GetMetricStatistics", params, cfg)
        if isinstance(root, dict):
            return root

        stat_names = [s.strip() for s in statistics.split(",") if s.strip()]
        datapoints = []
        for dp in root.findall(".//Datapoints/member"):
            ts = dp.find("Timestamp")
            unit = dp.find("Unit")
            point: dict[str, Any] = {"timestamp": ts.text if ts is not None else None}
            if unit is not None:
                point["unit"] = unit.text
            for stat in stat_names:
                el = dp.find(stat)
                if el is not None:
                    point[stat.lower()] = float(el.text)
            datapoints.append(point)
        # CloudWatch returns datapoints unordered; sort by timestamp for the caller.
        datapoints.sort(key=lambda p: p.get("timestamp") or "")
        return {"metric_name": metric_name, "count": len(datapoints), "datapoints": datapoints}

    @mcp.tool()
    def cloudwatch_list_alarms(state: str = "", max_records: int = 100) -> dict:
        """List CloudWatch alarms, optionally filtered by state.

        Args:
            state: Filter by alarm state: 'OK', 'ALARM', or 'INSUFFICIENT_DATA'. Empty = all.
            max_records: Maximum alarms to return (default 100).
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        valid = {"", "OK", "ALARM", "INSUFFICIENT_DATA"}
        if state not in valid:
            return {"error": f"state must be one of OK, ALARM, INSUFFICIENT_DATA (got '{state}')"}

        params: dict[str, Any] = {"MaxRecords": str(max_records)}
        if state:
            params["StateValue"] = state

        root = _cw_query("DescribeAlarms", params, cfg)
        if isinstance(root, dict):
            return root

        alarms = []
        for a in root.findall(".//MetricAlarms/member"):

            def _t(tag: str, node: ET.Element = a) -> Any:
                el = node.find(tag)
                return el.text if el is not None else None

            alarms.append(
                {
                    "name": _t("AlarmName"),
                    "state": _t("StateValue"),
                    "metric_name": _t("MetricName"),
                    "namespace": _t("Namespace"),
                    "reason": _t("StateReason"),
                }
            )
        return {"count": len(alarms), "alarms": alarms}

    @mcp.tool()
    def cloudwatch_start_logs_query(
        log_group: str,
        query: str,
        start_time: int,
        end_time: int,
        limit: int = 1000,
    ) -> dict:
        """Start a CloudWatch Logs Insights query. Returns a query_id to poll.

        Args:
            log_group: Log group name (e.g. '/aws/lambda/my-func').
            query: Logs Insights query string (e.g. 'fields @timestamp, @message | limit 20').
            start_time: Range start as Unix epoch seconds.
            end_time: Range end as Unix epoch seconds.
            limit: Maximum results (default 1000).
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        if not log_group or not query:
            return {"error": "log_group and query are required"}

        payload = {
            "logGroupName": log_group,
            "queryString": query,
            "startTime": int(start_time),
            "endTime": int(end_time),
            "limit": limit,
        }
        result = _logs_json("StartQuery", payload, cfg)
        if "error" in result:
            return result
        return {"query_id": result.get("queryId"), "status": "Running"}

    @mcp.tool()
    def cloudwatch_get_query_results(query_id: str) -> dict:
        """Poll results for a running Logs Insights query.

        Args:
            query_id: The query_id returned by cloudwatch_start_logs_query.
        """
        cfg = _get_config()
        if isinstance(cfg, dict):
            return cfg
        if not query_id:
            return {"error": "query_id is required"}

        result = _logs_json("GetQueryResults", {"queryId": query_id}, cfg)
        if "error" in result:
            return result

        # Each row is a list of {field, value} pairs; flatten to a plain dict.
        rows = [{f["field"]: f["value"] for f in row} for row in result.get("results", [])]
        return {
            "status": result.get("status"),
            "count": len(rows),
            "results": rows,
            "statistics": result.get("statistics", {}),
        }
