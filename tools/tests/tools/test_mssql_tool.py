"""Tests for mssql_tool - SQL Server database operations."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

ENV = {
    "MSSQL_SERVER": "test-server.database.windows.net",
    "MSSQL_DATABASE": "testdb",
    "MSSQL_USERNAME": "testuser",
    "MSSQL_PASSWORD": "testpass",
}


def _make_cursor(columns=None, rows=None, rowcount=0):
    """Build a mock pyodbc cursor."""
    cursor = MagicMock()
    if columns:
        cursor.description = [(col,) for col in columns]
        cursor.fetchmany.return_value = rows or []
        cursor.fetchall.return_value = rows or []
        cursor.fetchone.return_value = (len(rows),) if rows is not None else (0,)
    else:
        cursor.description = None
        cursor.rowcount = rowcount
        cursor.nextset.return_value = False
    return cursor


@pytest.fixture
def tool_fns(mcp: FastMCP):
    # Patch pyodbc to make it "available"
    pyodbc_mock = MagicMock()
    pyodbc_mock.Error = Exception

    with patch.dict("sys.modules", {"pyodbc": pyodbc_mock}):
        import importlib

        import aden_tools.tools.mssql_tool.mssql_tool as mod

        importlib.reload(mod)
        mod.register_tools(mcp, credentials=None)

    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestMssqlMissingCredentials:
    def test_execute_query_missing_server(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["mssql_execute_query"](query="SELECT 1")
        assert "error" in result
        assert "MSSQL_SERVER" in result["error"]

    def test_execute_query_missing_database(self, tool_fns):
        with patch.dict("os.environ", {"MSSQL_SERVER": "myserver"}, clear=True):
            result = tool_fns["mssql_execute_query"](query="SELECT 1")
        assert "error" in result
        assert "MSSQL_DATABASE" in result["error"]

    def test_execute_update_missing_server(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["mssql_execute_update"](query="UPDATE t SET x=1 WHERE id=1")
        assert "error" in result

    def test_get_schema_missing_server(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["mssql_get_schema"]()
        assert "error" in result


class TestMssqlQueryValidation:
    def test_empty_query_rejected(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["mssql_execute_query"](query="")
        assert "error" in result

    def test_non_select_query_rejected(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["mssql_execute_query"](query="DROP TABLE users")
        assert "error" in result

    def test_invalid_max_rows_rejected(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["mssql_execute_query"](query="SELECT 1", max_rows=0)
        assert "error" in result

    def test_delete_without_where_rejected(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["mssql_execute_update"](query="DELETE FROM users")
        assert "error" in result

    def test_empty_update_query_rejected(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["mssql_execute_update"](query="")
        assert "error" in result

    def test_empty_procedure_name_rejected(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["mssql_execute_procedure"](procedure_name="")
        assert "error" in result


def _patch_pyodbc(tool_fn, mock_conn):
    """Patch pyodbc in the tool closure's globals directly.

    Avoids beartype module-identity issues where re-importing the module
    returns a different object than what the tool closures reference.
    """
    new_pyodbc = MagicMock()
    new_pyodbc.Error = Exception
    new_pyodbc.connect.return_value = mock_conn
    return patch.dict(tool_fn.__globals__, {"pyodbc": new_pyodbc})


class TestMssqlExecuteQuery:
    def test_successful_select(self, tool_fns):
        cursor = _make_cursor(
            columns=["id", "name"],
            rows=[(1, "Alice"), (2, "Bob")],
        )
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = cursor

        with (
            patch.dict("os.environ", ENV),
            _patch_pyodbc(tool_fns["mssql_execute_query"], mock_conn),
        ):
            result = tool_fns["mssql_execute_query"](query="SELECT id, name FROM users")

        assert result["row_count"] == 2
        assert result["columns"] == ["id", "name"]

    def test_with_clause_allowed(self, tool_fns):
        cursor = _make_cursor(columns=["id"], rows=[(1,)])
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = cursor

        with (
            patch.dict("os.environ", ENV),
            _patch_pyodbc(tool_fns["mssql_execute_query"], mock_conn),
        ):
            result = tool_fns["mssql_execute_query"](
                query="WITH cte AS (SELECT 1) SELECT * FROM cte"
            )

        assert "error" not in result


class TestMssqlExecuteUpdate:
    def test_successful_insert(self, tool_fns):
        cursor = MagicMock()
        cursor.rowcount = 1
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = cursor

        with (
            patch.dict("os.environ", ENV),
            _patch_pyodbc(tool_fns["mssql_execute_update"], mock_conn),
        ):
            result = tool_fns["mssql_execute_update"](
                query="INSERT INTO users(name) VALUES('Alice')"
            )

        assert result["success"] is True
        assert result["affected_rows"] == 1

    def test_dry_run_rollback(self, tool_fns):
        cursor = MagicMock()
        cursor.rowcount = 5
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = cursor

        with (
            patch.dict("os.environ", ENV),
            _patch_pyodbc(tool_fns["mssql_execute_update"], mock_conn),
        ):
            result = tool_fns["mssql_execute_update"](
                query="UPDATE users SET active=0 WHERE id=1", commit=False
            )

        assert result["success"] is True
        assert result["committed"] is False
        mock_conn.rollback.assert_called_once()


class TestMssqlGetSchema:
    def test_list_tables(self, tool_fns):
        cursor = MagicMock()
        cursor.fetchall.return_value = [("users",), ("orders",)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = cursor

        with patch.dict("os.environ", ENV), _patch_pyodbc(tool_fns["mssql_get_schema"], mock_conn):
            result = tool_fns["mssql_get_schema"]()

        assert result["table_count"] == 2
        assert "users" in result["tables"]
