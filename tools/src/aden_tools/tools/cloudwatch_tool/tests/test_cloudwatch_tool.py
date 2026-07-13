"""
Tests for the AWS CloudWatch tool.

Covers:
- Credential/config validation
- SigV4 signer (Authorization header shape)
- XML parsing for list_metrics / get_metric_statistics / list_alarms
- Datapoint ordering and stat extraction
- Logs Insights start_query / get_query_results (JSON API)
- Error handling (missing creds, HTTP errors, state validation)
- register_tools registers all 5 tools
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from aden_tools.tools.cloudwatch_tool.cloudwatch_tool import (
    _get_config,
    _sigv4_headers,
    register_tools,
)

MOD = "aden_tools.tools.cloudwatch_tool.cloudwatch_tool"


def _tools(monkeypatch, with_creds=True):
    """Register tools against a mock mcp and return {name: fn}."""
    if with_creds:
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIATEST")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
        monkeypatch.setenv("AWS_REGION", "us-east-1")
    else:
        monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
        monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)

    fns: dict = {}
    mcp = MagicMock()
    mcp.tool.return_value = lambda fn: fns.__setitem__(fn.__name__, fn) or fn
    register_tools(mcp)
    return fns


def _resp(status=200, text="", json_body=None):
    r = MagicMock()
    r.status_code = status
    r.text = text
    r.json.return_value = json_body if json_body is not None else {}
    return r


LIST_METRICS_XML = """<ListMetricsResponse xmlns="http://monitoring.amazonaws.com/doc/2010-08-01/">
 <ListMetricsResult><Metrics><member>
   <Namespace>AWS/EC2</Namespace>
   <MetricName>CPUUtilization</MetricName>
   <Dimensions><member><Name>InstanceId</Name><Value>i-123</Value></member></Dimensions>
 </member></Metrics></ListMetricsResult>
</ListMetricsResponse>"""

STATS_XML = """<GetMetricStatisticsResponse xmlns="http://monitoring.amazonaws.com/doc/2010-08-01/">
 <GetMetricStatisticsResult><Datapoints>
   <member><Timestamp>2026-07-13T00:05:00Z</Timestamp><Average>5.0</Average><Unit>Percent</Unit></member>
   <member><Timestamp>2026-07-13T00:00:00Z</Timestamp><Average>3.0</Average><Unit>Percent</Unit></member>
 </Datapoints></GetMetricStatisticsResult>
</GetMetricStatisticsResponse>"""

ALARMS_XML = """<DescribeAlarmsResponse xmlns="http://monitoring.amazonaws.com/doc/2010-08-01/">
 <DescribeAlarmsResult><MetricAlarms><member>
   <AlarmName>cpu-high</AlarmName><StateValue>ALARM</StateValue>
   <MetricName>CPUUtilization</MetricName><Namespace>AWS/EC2</Namespace>
   <StateReason>threshold breached</StateReason>
 </member></MetricAlarms></DescribeAlarmsResult>
</DescribeAlarmsResponse>"""


# --- config + signer ---


def test_get_config_missing_creds(monkeypatch):
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    cfg = _get_config()
    assert isinstance(cfg, dict)
    assert "error" in cfg


def test_sigv4_headers_shape():
    headers = _sigv4_headers(
        "GET",
        "monitoring",
        "monitoring.us-east-1.amazonaws.com",
        "us-east-1",
        "AKIATEST",
        "secret",
        {"Action": "ListMetrics"},
        b"",
    )
    assert headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=AKIATEST/")
    assert "monitoring/aws4_request" in headers["Authorization"]
    assert "x-amz-date" in headers


def test_tools_require_creds(monkeypatch):
    fns = _tools(monkeypatch, with_creds=False)
    assert "error" in fns["cloudwatch_list_metrics"](namespace="AWS/EC2")


# --- metrics ---


def test_list_metrics_parses_xml(monkeypatch):
    fns = _tools(monkeypatch)
    with patch(f"{MOD}.httpx.get", return_value=_resp(text=LIST_METRICS_XML)):
        out = fns["cloudwatch_list_metrics"](namespace="AWS/EC2")
    assert out["count"] == 1
    m = out["metrics"][0]
    assert m["metric_name"] == "CPUUtilization"
    assert m["dimensions"][0] == {"name": "InstanceId", "value": "i-123"}


def test_list_metrics_requires_namespace(monkeypatch):
    fns = _tools(monkeypatch)
    assert "error" in fns["cloudwatch_list_metrics"](namespace="")


def test_get_metric_statistics_sorted(monkeypatch):
    fns = _tools(monkeypatch)
    with patch(f"{MOD}.httpx.get", return_value=_resp(text=STATS_XML)):
        out = fns["cloudwatch_get_metric_statistics"](
            namespace="AWS/EC2",
            metric_name="CPUUtilization",
            start_time="2026-07-13T00:00:00Z",
            end_time="2026-07-13T01:00:00Z",
            statistics="Average",
        )
    assert out["count"] == 2
    # Datapoints must be returned in ascending timestamp order.
    assert [d["timestamp"] for d in out["datapoints"]] == [
        "2026-07-13T00:00:00Z",
        "2026-07-13T00:05:00Z",
    ]
    assert out["datapoints"][0]["average"] == 3.0


def test_get_metric_statistics_validates(monkeypatch):
    fns = _tools(monkeypatch)
    assert "error" in fns["cloudwatch_get_metric_statistics"](
        namespace="AWS/EC2",
        metric_name="",
        start_time="a",
        end_time="b",
    )


def test_http_error_propagates(monkeypatch):
    fns = _tools(monkeypatch)
    with patch(f"{MOD}.httpx.get", return_value=_resp(status=400, text="<ErrorResponse/>")):
        out = fns["cloudwatch_list_metrics"](namespace="AWS/EC2")
    assert "error" in out and "400" in out["error"]


# --- alarms ---


def test_list_alarms_parses_and_filters(monkeypatch):
    fns = _tools(monkeypatch)
    with patch(f"{MOD}.httpx.get", return_value=_resp(text=ALARMS_XML)) as mock_get:
        out = fns["cloudwatch_list_alarms"](state="ALARM")
    assert out["count"] == 1
    assert out["alarms"][0]["name"] == "cpu-high"
    assert out["alarms"][0]["state"] == "ALARM"
    # State filter must be forwarded to the API call.
    assert mock_get.call_args.kwargs["params"]["StateValue"] == "ALARM"


def test_list_alarms_bad_state(monkeypatch):
    fns = _tools(monkeypatch)
    assert "error" in fns["cloudwatch_list_alarms"](state="BOGUS")


# --- logs insights (JSON API) ---


def test_start_logs_query(monkeypatch):
    fns = _tools(monkeypatch)
    with patch(f"{MOD}.httpx.post", return_value=_resp(json_body={"queryId": "q-1"})):
        out = fns["cloudwatch_start_logs_query"](
            log_group="/aws/lambda/f",
            query="fields @message",
            start_time=1,
            end_time=2,
        )
    assert out["query_id"] == "q-1"


def test_get_query_results_flattens(monkeypatch):
    fns = _tools(monkeypatch)
    body = {
        "status": "Complete",
        "results": [[{"field": "@message", "value": "hi"}, {"field": "@timestamp", "value": "t"}]],
        "statistics": {"recordsMatched": 1},
    }
    with patch(f"{MOD}.httpx.post", return_value=_resp(json_body=body)):
        out = fns["cloudwatch_get_query_results"](query_id="q-1")
    assert out["status"] == "Complete"
    assert out["count"] == 1
    assert out["results"][0] == {"@message": "hi", "@timestamp": "t"}


# --- registration ---


def test_register_tools_registers_all(monkeypatch):
    fns = _tools(monkeypatch)
    assert set(fns) == {
        "cloudwatch_list_metrics",
        "cloudwatch_get_metric_statistics",
        "cloudwatch_list_alarms",
        "cloudwatch_start_logs_query",
        "cloudwatch_get_query_results",
    }
