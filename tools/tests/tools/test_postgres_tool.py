"""
Tests for PostgreSQL MCP tools (refactored single-file version).
"""

import psycopg2 as psycopg
import pytest
from fastmcp import FastMCP

from aden_tools.tools.postgres_tool import register_tools


@pytest.fixture
def mcp():
    return FastMCP("test-server")


@pytest.fixture(autouse=True)
def _mock_database_url(monkeypatch):
    """
    Prevent DATABASE_URL requirement during tests.
    """
    monkeypatch.setattr(
        "aden_tools.tools.postgres_tool.postgres_tool._get_database_url",
        lambda credentials: "postgresql://fake-url",
    )


# ============================================================
# Database Mocking
# ============================================================


def _mock_db(monkeypatch):
    class FakeCursor:
        description = [type("D", (), {"name": "col"})]

        def execute(self, *args, **kwargs):
            pass

        def fetchmany(self, n):
            return [["value"]]

        def fetchall(self):
            return [
                ("public",),
                ("example_schema",),
            ]

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class FakeConn:
        def set_session(self, **kwargs):
            pass  # needed because readonly=True is called

        def cursor(self):
            return FakeCursor()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(
        "aden_tools.tools.postgres_tool.postgres_tool._get_connection",
        lambda database_url: FakeConn(),
    )


@pytest.fixture
def pg_query_fn(mcp: FastMCP, monkeypatch):
    _mock_db(monkeypatch)
    register_tools(mcp)
    return mcp._tool_manager._tools["pg_query"].fn


@pytest.fixture
def pg_list_schemas_fn(mcp: FastMCP, monkeypatch):
    _mock_db(monkeypatch)
    register_tools(mcp)
    return mcp._tool_manager._tools["pg_list_schemas"].fn


@pytest.fixture
def pg_list_tables_fn(mcp: FastMCP, monkeypatch):
    _mock_db(monkeypatch)
    register_tools(mcp)
    return mcp._tool_manager._tools["pg_list_tables"].fn


@pytest.fixture
def pg_describe_table_fn(mcp: FastMCP, monkeypatch):
    _mock_db(monkeypatch)
    register_tools(mcp)
    return mcp._tool_manager._tools["pg_describe_table"].fn


@pytest.fixture
def pg_explain_fn(mcp: FastMCP, monkeypatch):
    _mock_db(monkeypatch)
    register_tools(mcp)
    return mcp._tool_manager._tools["pg_explain"].fn


# ============================================================
# Tests
# ============================================================


class TestPgQuery:
    def test_simple_select(self, pg_query_fn):
        result = pg_query_fn(sql="SELECT 1")

        assert result["success"] is True
        assert result["row_count"] == 1
        assert isinstance(result["columns"], list)
        assert isinstance(result["rows"], list)

    def test_invalid_sql_returns_error(self, pg_query_fn, monkeypatch):
        monkeypatch.setattr(
            "aden_tools.tools.postgres_tool.postgres_tool.validate_sql",
            lambda _: (_ for _ in ()).throw(ValueError("Invalid SQL")),
        )

        result = pg_query_fn(sql="DROP TABLE x")

        assert result["success"] is False
        assert "error" in result

    def test_query_timeout(self, pg_query_fn, monkeypatch):
        class TimeoutCursor:
            def execute(self, *args, **kwargs):
                raise psycopg.errors.QueryCanceled()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        class TimeoutConn:
            def set_session(self, **kwargs):
                pass

            def cursor(self):
                return TimeoutCursor()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        monkeypatch.setattr(
            "aden_tools.tools.postgres_tool.postgres_tool._get_connection",
            lambda database_url: TimeoutConn(),
        )

        result = pg_query_fn(sql="SELECT pg_sleep(10)")

        assert result["success"] is False
        assert "timed out" in result["error"].lower()


class TestPgListSchemas:
    def test_list_schemas_success(self, pg_list_schemas_fn):
        result = pg_list_schemas_fn()

        assert result["success"] is True
        assert isinstance(result["result"], list)
        assert all(isinstance(x, str) for x in result["result"])


class TestPgListTables:
    def test_list_tables_all(self, pg_list_tables_fn):
        result = pg_list_tables_fn()
        assert result["success"] is True
        assert isinstance(result["result"], list)

    def test_list_tables_with_schema(self, pg_list_tables_fn):
        result = pg_list_tables_fn(schema="any_schema")
        assert result["success"] is True
        assert isinstance(result["result"], list)


class TestPgDescribeTable:
    def test_describe_table_success(self, pg_describe_table_fn, monkeypatch):
        class DescribeCursor:
            def execute(self, *args, **kwargs):
                pass

            def fetchall(self):
                return [
                    ("col_a", "bigint", False, None),
                    ("col_b", "text", True, "default"),
                ]

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        class DescribeConn:
            def set_session(self, **kwargs):
                pass

            def cursor(self):
                return DescribeCursor()

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        monkeypatch.setattr(
            "aden_tools.tools.postgres_tool.postgres_tool._get_connection",
            lambda database_url: DescribeConn(),
        )

        result = pg_describe_table_fn(
            schema="any_schema",
            table="any_table",
        )

        assert result["success"] is True
        assert isinstance(result["result"], list)
        assert len(result["result"]) == 2

        column = result["result"][0]
        assert set(column.keys()) == {"column", "type", "nullable", "default"}


class TestPgExplain:
    def test_explain_success(self, pg_explain_fn):
        result = pg_explain_fn(sql="SELECT 1")

        assert result["success"] is True
        assert isinstance(result["result"], list)

    def test_explain_invalid_sql(self, pg_explain_fn, monkeypatch):
        monkeypatch.setattr(
            "aden_tools.tools.postgres_tool.postgres_tool.validate_sql",
            lambda _: (_ for _ in ()).throw(ValueError("Invalid SQL")),
        )

        result = pg_explain_fn(sql="DELETE FROM x")

        assert result["success"] is False
        assert "error" in result
