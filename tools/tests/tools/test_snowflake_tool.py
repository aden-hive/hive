"""Tests for snowflake_tool - Snowflake SQL REST API."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.snowflake_tool.snowflake_tool import register_tools

ENV = {"SNOWFLAKE_ACCOUNT": "xy12345.us-east-1", "SNOWFLAKE_TOKEN": "test-token"}


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


class TestSnowflakeExecuteSQL:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["snowflake_execute_sql"](statement="SELECT 1")
        assert "error" in result

    def test_missing_statement(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["snowflake_execute_sql"](statement="")
        assert "error" in result

    def test_successful_sync_query(self, tool_fns):
        data = {
            "statementHandle": "handle-123",
            "resultSetMetaData": {
                "numRows": 2,
                "rowType": [
                    {"name": "ID", "type": "fixed"},
                    {"name": "NAME", "type": "text"},
                ],
            },
            "data": [["1", "Alice"], ["2", "Bob"]],
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.snowflake_tool.snowflake_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["snowflake_execute_sql"](statement="SELECT * FROM users")

        assert result["status"] == "complete"
        assert result["num_rows"] == 2
        assert result["columns"] == ["ID", "NAME"]
        assert result["rows"] == [["1", "Alice"], ["2", "Bob"]]

    def test_async_query(self, tool_fns):
        data = {
            "statementHandle": "handle-456",
            "message": "Asynchronous execution in progress.",
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.snowflake_tool.snowflake_tool.httpx.post",
                return_value=_mock_resp(data, 202),
            ),
        ):
            result = tool_fns["snowflake_execute_sql"](statement="SELECT * FROM big_table")

        assert result["status"] == "running"
        assert result["statement_handle"] == "handle-456"


class TestSnowflakeGetStatementStatus:
    def test_missing_handle(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["snowflake_get_statement_status"](statement_handle="")
        assert "error" in result

    def test_complete_result(self, tool_fns):
        data = {
            "statementHandle": "handle-123",
            "resultSetMetaData": {
                "numRows": 1,
                "rowType": [{"name": "COUNT", "type": "fixed"}],
            },
            "data": [["42"]],
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.snowflake_tool.snowflake_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["snowflake_get_statement_status"](statement_handle="handle-123")

        assert result["status"] == "complete"
        assert result["rows"] == [["42"]]

    def test_still_running(self, tool_fns):
        data = {
            "statementHandle": "handle-456",
            "message": "Still executing",
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.snowflake_tool.snowflake_tool.httpx.get",
                return_value=_mock_resp(data, 202),
            ),
        ):
            result = tool_fns["snowflake_get_statement_status"](statement_handle="handle-456")

        assert result["status"] == "running"

    def test_query_error(self, tool_fns):
        data = {
            "statementHandle": "handle-789",
            "message": "SQL compilation error",
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.snowflake_tool.snowflake_tool.httpx.get",
                return_value=_mock_resp(data, 422),
            ),
        ):
            result = tool_fns["snowflake_get_statement_status"](statement_handle="handle-789")

        assert result["status"] == "error"
        assert "SQL compilation" in result["message"]


class TestSnowflakeCancelStatement:
    def test_missing_handle(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["snowflake_cancel_statement"](statement_handle="")
        assert "error" in result

    def test_successful_cancel(self, tool_fns):
        data = {"statementHandle": "handle-123"}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.snowflake_tool.snowflake_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["snowflake_cancel_statement"](statement_handle="handle-123")

        assert result["result"] == "cancelled"
