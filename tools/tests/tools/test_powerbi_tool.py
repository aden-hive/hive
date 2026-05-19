"""Tests for powerbi_tool - Power BI workspace, dataset, and report management."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.powerbi_tool.powerbi_tool import register_tools

ENV = {"POWERBI_ACCESS_TOKEN": "test-token"}


def _mock_resp(data, status_code=200, headers=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = ""
    resp.content = b"ok" if data else b""
    resp.headers = headers or {}
    return resp


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestPowerBIListWorkspaces:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["powerbi_list_workspaces"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {
            "value": [
                {
                    "id": "f089354e-8366-4e18-aea3-4cb4a3a50b48",
                    "name": "Marketing",
                    "isReadOnly": False,
                    "isOnDedicatedCapacity": True,
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.powerbi_tool.powerbi_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["powerbi_list_workspaces"]()

        assert result["count"] == 1
        assert result["workspaces"][0]["name"] == "Marketing"
        assert result["workspaces"][0]["is_on_dedicated_capacity"] is True


class TestPowerBIListDatasets:
    def test_missing_workspace(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["powerbi_list_datasets"](workspace_id="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {
            "value": [
                {
                    "id": "cfafbeb1-8037-4d0c-896e-a46fb27ff229",
                    "name": "SalesMarketing",
                    "configuredBy": "john@contoso.com",
                    "isRefreshable": True,
                    "createdDate": "2024-01-15T10:30:00Z",
                    "description": "Sales data",
                    "webUrl": "https://app.powerbi.com/...",
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.powerbi_tool.powerbi_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["powerbi_list_datasets"](workspace_id="ws-123")

        assert result["count"] == 1
        assert result["datasets"][0]["name"] == "SalesMarketing"
        assert result["datasets"][0]["is_refreshable"] is True


class TestPowerBIListReports:
    def test_missing_workspace(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["powerbi_list_reports"](workspace_id="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {
            "value": [
                {
                    "id": "5b218778-e7a5-4d73-8187-f10824047715",
                    "name": "SalesReport",
                    "datasetId": "cfafbeb1-8037-4d0c-896e-a46fb27ff229",
                    "reportType": "PowerBIReport",
                    "webUrl": "https://app.powerbi.com/...",
                    "description": "Sales overview",
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.powerbi_tool.powerbi_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["powerbi_list_reports"](workspace_id="ws-123")

        assert result["count"] == 1
        assert result["reports"][0]["name"] == "SalesReport"
        assert result["reports"][0]["report_type"] == "PowerBIReport"


class TestPowerBIRefreshDataset:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["powerbi_refresh_dataset"](workspace_id="", dataset_id="")
        assert "error" in result

    def test_successful_refresh(self, tool_fns):
        resp = _mock_resp({}, status_code=202, headers={"x-ms-request-id": "req-123"})
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.powerbi_tool.powerbi_tool.httpx.post", return_value=resp),
        ):
            result = tool_fns["powerbi_refresh_dataset"](workspace_id="ws-123", dataset_id="ds-456")

        assert result["result"] == "accepted"


class TestPowerBIGetRefreshHistory:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["powerbi_get_refresh_history"](workspace_id="", dataset_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "value": [
                {
                    "requestId": "req-123",
                    "refreshType": "ViaApi",
                    "status": "Completed",
                    "startTime": "2024-01-15T09:25:43Z",
                    "endTime": "2024-01-15T09:31:43Z",
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.powerbi_tool.powerbi_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["powerbi_get_refresh_history"](
                workspace_id="ws-123", dataset_id="ds-456"
            )

        assert result["count"] == 1
        assert result["refreshes"][0]["status"] == "Completed"
        assert result["refreshes"][0]["refresh_type"] == "ViaApi"
