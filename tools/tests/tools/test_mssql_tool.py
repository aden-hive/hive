"""Tests for mssql_tool - Microsoft SQL Server query execution."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.mssql_tool.mssql_tool import register_tools


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestMssqlTool:

    def test_missing_params(self, tool_fns):
        result = tool_fns["mssql_query"](server="", database="", query="")
        assert "error" in result

    def test_connection_error(self, tool_fns):
        with patch(
            "aden_tools.tools.mssql_tool.mssql_tool.pyodbc.connect",
            side_effect=Exception("connection failed"),
        ):
            result = tool_fns["mssql_query"](
                server="localhost",
                database="test",
                query="SELECT 1",
            )

        assert "error" in result

    def test_successful_query(self, tool_fns):
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [(1, "test")]

        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch(
            "aden_tools.tools.mssql_tool.mssql_tool.pyodbc.connect",
            return_value=mock_conn,
        ):
            result = tool_fns["mssql_query"](
                server="localhost",
                database="test",
                query="SELECT 1",
            )

        assert result["rows"][0][0] == 1