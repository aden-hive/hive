"""Tests for datadog_tool — metrics, monitors, events, and log search."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.datadog_tool.datadog_tool import register_tools

ENV = {
    "DATADOG_API_KEY": "test-api-key",
    "DATADOG_APP_KEY": "test-app-key",
}
ENV_API_ONLY = {"DATADOG_API_KEY": "test-api-key"}


def _mock_resp(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = ""
    return resp


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


# ---------------------------------------------------------------------------
# datadog_query_metrics
# ---------------------------------------------------------------------------

class TestDatadogQueryMetrics:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["datadog_query_metrics"](
                query="avg:system.cpu.user{*}", from_time=1700000000, to_time=1700003600
            )
        assert "error" in result

    def test_missing_app_key(self, tool_fns):
        with patch.dict("os.environ", ENV_API_ONLY, clear=True):
            result = tool_fns["datadog_query_metrics"](
                query="avg:system.cpu.user{*}", from_time=1700000000, to_time=1700003600
            )
        assert "error" in result

    def test_empty_query(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["datadog_query_metrics"](
                query="", from_time=1700000000, to_time=1700003600
            )
        assert "error" in result

    def test_successful_query(self, tool_fns):
        data = {
            "status": "ok",
            "from_date": 1700000000000,
            "to_date": 1700003600000,
            "series": [
                {
                    "metric": "system.cpu.user",
                    "display_name": "system.cpu.user",
                    "unit": [{"name": "percent"}],
                    "pointlist": [[1700000000000, 12.5], [1700001000000, 14.0]],
                    "scope": "host:web-01",
                    "length": 2,
                }
            ],
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.datadog_tool.datadog_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["datadog_query_metrics"](
                query="avg:system.cpu.user{*}", from_time=1700000000, to_time=1700003600
            )

        assert result["status"] == "ok"
        assert result["series_count"] == 1
        assert result["series"][0]["metric"] == "system.cpu.user"
        assert result["series"][0]["unit"] == "percent"
        assert len(result["series"][0]["pointlist"]) == 2

    def test_api_error_propagated(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.datadog_tool.datadog_tool.httpx.get",
                return_value=_mock_resp({"errors": ["Forbidden"]}, 403),
            ),
        ):
            result = tool_fns["datadog_query_metrics"](
                query="avg:system.cpu.user{*}", from_time=1700000000, to_time=1700003600
            )
        assert "error" in result


# ---------------------------------------------------------------------------
# datadog_list_monitors
# ---------------------------------------------------------------------------

MONITOR_DATA = {
    "id": 12345,
    "name": "High CPU on web servers",
    "type": "metric alert",
    "overall_state": "Alert",
    "query": "avg(last_5m):avg:system.cpu.user{env:prod} > 90",
    "message": "CPU usage is high @pagerduty",
    "tags": ["env:prod", "team:ops"],
    "created": "2024-01-01T00:00:00.000Z",
    "modified": "2024-06-01T00:00:00.000Z",
}


class TestDatadogListMonitors:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["datadog_list_monitors"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.datadog_tool.datadog_tool.httpx.get",
                return_value=_mock_resp([MONITOR_DATA]),
            ),
        ):
            result = tool_fns["datadog_list_monitors"]()

        assert result["count"] == 1
        assert result["monitors"][0]["name"] == "High CPU on web servers"
        assert result["monitors"][0]["status"] == "Alert"

    def test_filters_passed_as_params(self, tool_fns):
        captured = {}

        def fake_get(url, headers, params=None, timeout=30):
            captured["params"] = params
            return _mock_resp([])

        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.datadog_tool.datadog_tool.httpx.get",
                side_effect=fake_get,
            ),
        ):
            tool_fns["datadog_list_monitors"](name="CPU", tags="env:prod", limit=10)

        assert captured["params"]["name"] == "CPU"
        assert captured["params"]["tags"] == "env:prod"
        assert captured["params"]["page_size"] == 10

    def test_limit_capped_at_1000(self, tool_fns):
        captured = {}

        def fake_get(url, headers, params=None, timeout=30):
            captured["params"] = params
            return _mock_resp([])

        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.datadog_tool.datadog_tool.httpx.get",
                side_effect=fake_get,
            ),
        ):
            tool_fns["datadog_list_monitors"](limit=9999)

        assert captured["params"]["page_size"] == 1000


# ---------------------------------------------------------------------------
# datadog_get_monitor
# ---------------------------------------------------------------------------

class TestDatadogGetMonitor:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["datadog_get_monitor"](monitor_id=12345)
        assert "error" in result

    def test_successful_get(self, tool_fns):
        detail = dict(MONITOR_DATA)
        detail["creator"] = {"email": "admin@example.com"}
        detail["options"] = {"thresholds": {"critical": 90}}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.datadog_tool.datadog_tool.httpx.get",
                return_value=_mock_resp(detail),
            ),
        ):
            result = tool_fns["datadog_get_monitor"](monitor_id=12345)

        assert result["id"] == 12345
        assert result["name"] == "High CPU on web servers"
        assert result["creator"] == "admin@example.com"
        assert result["options"] == {"thresholds": {"critical": 90}}

    def test_not_found_returns_error(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.datadog_tool.datadog_tool.httpx.get",
                return_value=_mock_resp({"errors": ["Not Found"]}, 404),
            ),
        ):
            result = tool_fns["datadog_get_monitor"](monitor_id=99999)
        assert "error" in result


# ---------------------------------------------------------------------------
# datadog_mute_monitor
# ---------------------------------------------------------------------------

class TestDatadogMuteMonitor:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["datadog_mute_monitor"](monitor_id=12345)
        assert "error" in result

    def test_successful_mute(self, tool_fns):
        muted = dict(MONITOR_DATA)
        muted["overall_state"] = "Ignored"
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.datadog_tool.datadog_tool.httpx.post",
                return_value=_mock_resp(muted),
            ),
        ):
            result = tool_fns["datadog_mute_monitor"](monitor_id=12345)

        assert result["result"] == "muted"
        assert result["id"] == 12345

    def test_mute_with_scope_and_end(self, tool_fns):
        captured = {}

        def fake_post(url, headers, json=None, timeout=30):
            captured["body"] = json
            return _mock_resp(MONITOR_DATA)

        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.datadog_tool.datadog_tool.httpx.post",
                side_effect=fake_post,
            ),
        ):
            tool_fns["datadog_mute_monitor"](
                monitor_id=12345, scope="host:web-01", end=1700010000
            )

        assert captured["body"]["scope"] == "host:web-01"
        assert captured["body"]["end"] == 1700010000


# ---------------------------------------------------------------------------
# datadog_list_events
# ---------------------------------------------------------------------------

EVENT_DATA = {
    "id": 987654321,
    "title": "Deploy finished",
    "text": "Version 2.0 deployed to production",
    "date_happened": 1700001000,
    "source_type_name": "my-deploy-tool",
    "priority": "normal",
    "alert_type": "info",
    "tags": ["env:prod"],
    "host": "deploy-host",
}


class TestDatadogListEvents:
    def test_missing_api_key(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["datadog_list_events"](start=1700000000, end=1700003600)
        assert "error" in result

    def test_successful_list(self, tool_fns):
        # events endpoint only needs API key
        with (
            patch.dict("os.environ", ENV_API_ONLY),
            patch(
                "aden_tools.tools.datadog_tool.datadog_tool.httpx.get",
                return_value=_mock_resp({"events": [EVENT_DATA]}),
            ),
        ):
            result = tool_fns["datadog_list_events"](start=1700000000, end=1700003600)

        assert result["count"] == 1
        assert result["events"][0]["title"] == "Deploy finished"
        assert result["events"][0]["source"] == "my-deploy-tool"

    def test_filters_passed(self, tool_fns):
        captured = {}

        def fake_get(url, headers, params=None, timeout=30):
            captured["params"] = params
            return _mock_resp({"events": []})

        with (
            patch.dict("os.environ", ENV_API_ONLY),
            patch(
                "aden_tools.tools.datadog_tool.datadog_tool.httpx.get",
                side_effect=fake_get,
            ),
        ):
            tool_fns["datadog_list_events"](
                start=1700000000,
                end=1700003600,
                tags="env:prod",
                priority="normal",
                limit=25,
            )

        assert captured["params"]["tags"] == "env:prod"
        assert captured["params"]["priority"] == "normal"
        assert captured["params"]["count"] == 25


# ---------------------------------------------------------------------------
# datadog_search_logs
# ---------------------------------------------------------------------------

LOG_DATA = {
    "id": "AAAAAAAAAAAAAAAAAAAAAAAAAAbcd1234",
    "attributes": {
        "timestamp": "2024-06-15T12:00:00.000Z",
        "status": "error",
        "service": "web",
        "host": "web-01",
        "message": "NullPointerException in Controller",
        "tags": ["env:prod", "version:2.0"],
    },
}


class TestDatadogSearchLogs:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["datadog_search_logs"](query="service:web")
        assert "error" in result

    def test_missing_app_key(self, tool_fns):
        with patch.dict("os.environ", ENV_API_ONLY, clear=True):
            result = tool_fns["datadog_search_logs"](query="service:web")
        assert "error" in result

    def test_successful_search(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.datadog_tool.datadog_tool.httpx.post",
                return_value=_mock_resp({"data": [LOG_DATA], "meta": {}}),
            ),
        ):
            result = tool_fns["datadog_search_logs"](query="service:web status:error")

        assert result["count"] == 1
        assert result["logs"][0]["service"] == "web"
        assert result["logs"][0]["status"] == "error"
        assert "NullPointerException" in result["logs"][0]["message"]

    def test_request_body_built_correctly(self, tool_fns):
        captured = {}

        def fake_post(url, headers, json=None, timeout=30):
            captured["body"] = json
            return _mock_resp({"data": [], "meta": {}})

        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.datadog_tool.datadog_tool.httpx.post",
                side_effect=fake_post,
            ),
        ):
            tool_fns["datadog_search_logs"](
                query="service:api",
                from_time="now-1h",
                to_time="now",
                limit=100,
                sort="-timestamp",
            )

        body = captured["body"]
        assert body["filter"]["query"] == "service:api"
        assert body["filter"]["from"] == "now-1h"
        assert body["page"]["limit"] == 100
        assert body["sort"] == "-timestamp"

    def test_limit_capped_at_1000(self, tool_fns):
        captured = {}

        def fake_post(url, headers, json=None, timeout=30):
            captured["body"] = json
            return _mock_resp({"data": [], "meta": {}})

        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.datadog_tool.datadog_tool.httpx.post",
                side_effect=fake_post,
            ),
        ):
            tool_fns["datadog_search_logs"](limit=5000)

        assert captured["body"]["page"]["limit"] == 1000
