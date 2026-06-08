"""Tests for pagerduty_tool - Incident management and services."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.pagerduty_tool.pagerduty_tool import register_tools

ENV = {
    "PAGERDUTY_API_KEY": "test-api-key",
    "PAGERDUTY_FROM_EMAIL": "agent@example.com",
}


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


INCIDENT_DATA = {
    "id": "PT4KHLK",
    "incident_number": 1234,
    "title": "Server is on fire",
    "status": "triggered",
    "urgency": "high",
    "created_at": "2024-01-15T10:00:00Z",
    "html_url": "https://acme.pagerduty.com/incidents/PT4KHLK",
    "service": {"id": "PWIXJZS", "summary": "Web Service"},
    "assignments": [{"assignee": {"summary": "John Doe"}}],
}


class TestPagerdutyListIncidents:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["pagerduty_list_incidents"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {"incidents": [INCIDENT_DATA], "more": False}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.pagerduty_tool.pagerduty_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["pagerduty_list_incidents"]()

        assert result["count"] == 1
        assert result["incidents"][0]["title"] == "Server is on fire"
        assert result["incidents"][0]["service"] == "Web Service"


class TestPagerdutyGetIncident:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["pagerduty_get_incident"](incident_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        inc = dict(INCIDENT_DATA)
        inc["body"] = {"details": "CPU at 100%"}
        data = {"incident": inc}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.pagerduty_tool.pagerduty_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["pagerduty_get_incident"](incident_id="PT4KHLK")

        assert result["title"] == "Server is on fire"
        assert result["details"] == "CPU at 100%"


class TestPagerdutyCreateIncident:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["pagerduty_create_incident"](title="", service_id="")
        assert "error" in result

    def test_successful_create(self, tool_fns):
        data = {"incident": INCIDENT_DATA}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.pagerduty_tool.pagerduty_tool.httpx.post",
                return_value=_mock_resp(data, 201),
            ),
        ):
            result = tool_fns["pagerduty_create_incident"](title="Server is on fire", service_id="PWIXJZS")

        assert result["result"] == "created"
        assert result["id"] == "PT4KHLK"


class TestPagerdutyUpdateIncident:
    def test_missing_status(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["pagerduty_update_incident"](incident_id="PT4KHLK", status="")
        assert "error" in result

    def test_successful_acknowledge(self, tool_fns):
        ack = dict(INCIDENT_DATA)
        ack["status"] = "acknowledged"
        data = {"incident": ack}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.pagerduty_tool.pagerduty_tool.httpx.put",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["pagerduty_update_incident"](incident_id="PT4KHLK", status="acknowledged")

        assert result["status"] == "acknowledged"


class TestPagerdutyListServices:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["pagerduty_list_services"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {
            "services": [
                {
                    "id": "PWIXJZS",
                    "name": "Web Service",
                    "description": "Production web app",
                    "status": "active",
                    "html_url": "https://acme.pagerduty.com/services/PWIXJZS",
                    "created_at": "2024-01-01T00:00:00Z",
                    "last_incident_timestamp": "2024-06-15T12:30:00Z",
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.pagerduty_tool.pagerduty_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["pagerduty_list_services"]()

        assert result["count"] == 1
        assert result["services"][0]["name"] == "Web Service"
