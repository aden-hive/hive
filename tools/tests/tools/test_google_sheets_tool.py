"""Tests for google_sheets_tool - Spreadsheet data access."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.google_sheets_tool.google_sheets_tool import register_tools

ENV = {"GOOGLE_ACCESS_TOKEN": "test-token"}


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


class TestSheetsGetSpreadsheet:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["google_sheets_get_spreadsheet"](spreadsheet_id="abc123")
        assert "error" in result

    def test_missing_id(self, tool_fns):
        """Empty spreadsheet_id still makes the API call; the tool doesn't validate it."""
        with patch.dict("os.environ", ENV):
            with patch(
                "aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.get",
                return_value=_mock_resp({"error": {"message": "not found"}}, status_code=404),
            ):
                result = tool_fns["google_sheets_get_spreadsheet"](spreadsheet_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "spreadsheetId": "abc123",
            "properties": {"title": "My Spreadsheet"},
            "sheets": [
                {
                    "properties": {
                        "title": "Sheet1",
                        "sheetId": 0,
                        "index": 0,
                        "gridProperties": {"rowCount": 1000, "columnCount": 26},
                    }
                }
            ],
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["google_sheets_get_spreadsheet"](spreadsheet_id="abc123")

        assert result["properties"]["title"] == "My Spreadsheet"
        assert len(result["sheets"]) == 1
        assert result["sheets"][0]["properties"]["title"] == "Sheet1"


class TestSheetsGetValues:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["google_sheets_get_values"](spreadsheet_id="abc", range_name="Sheet1!A1:B2")
        assert "error" in result

    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            with patch(
                "aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.get",
                return_value=_mock_resp({"error": {"message": "not found"}}, status_code=404),
            ):
                result = tool_fns["google_sheets_get_values"](spreadsheet_id="", range_name="")
        assert "error" in result

    def test_successful_read(self, tool_fns):
        data = {
            "range": "Sheet1!A1:B3",
            "majorDimension": "ROWS",
            "values": [
                ["Name", "Score"],
                ["Alice", "95"],
                ["Bob", "87"],
            ],
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.google_sheets_tool.google_sheets_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["google_sheets_get_values"](spreadsheet_id="abc123", range_name="Sheet1!A1:B3")

        assert len(result["values"]) == 3
        assert result["values"][0] == ["Name", "Score"]
