"""Tests for redshift_tool - Amazon Redshift Data API."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.redshift_tool.redshift_tool import register_tools

ENV = {
    "AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE",
    "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "AWS_REGION": "us-east-1",
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


class TestRedshiftExecuteSQL:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["redshift_execute_sql"](sql="SELECT 1", database="dev", cluster_identifier="my-cluster")
        assert "error" in result

    def test_missing_sql(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["redshift_execute_sql"](sql="", database="dev", cluster_identifier="my-cluster")
        assert "error" in result

    def test_missing_cluster(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["redshift_execute_sql"](sql="SELECT 1", database="dev")
        assert "error" in result

    def test_successful_execute(self, tool_fns):
        data = {
            "Id": "stmt-abc123",
            "CreatedAt": 1598323200.0,
            "Database": "dev",
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.redshift_tool.redshift_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["redshift_execute_sql"](
                sql="SELECT * FROM users", database="dev", cluster_identifier="my-cluster"
            )

        assert result["statement_id"] == "stmt-abc123"
        assert result["status"] == "submitted"


class TestRedshiftDescribeStatement:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["redshift_describe_statement"](statement_id="")
        assert "error" in result

    def test_successful_describe(self, tool_fns):
        data = {
            "Id": "stmt-abc123",
            "Status": "FINISHED",
            "HasResultSet": True,
            "ResultRows": 10,
            "Duration": 1500000000,
            "QueryString": "SELECT * FROM users",
            "Error": "",
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.redshift_tool.redshift_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["redshift_describe_statement"](statement_id="stmt-abc123")

        assert result["status"] == "FINISHED"
        assert result["has_result_set"] is True
        assert result["result_rows"] == 10


class TestRedshiftGetResults:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["redshift_get_results"](statement_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "ColumnMetadata": [
                {"name": "id", "typeName": "int4"},
                {"name": "email", "typeName": "varchar"},
            ],
            "Records": [
                [{"longValue": 1}, {"stringValue": "alice@example.com"}],
                [{"longValue": 2}, {"stringValue": "bob@example.com"}],
            ],
            "TotalNumRows": 2,
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.redshift_tool.redshift_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["redshift_get_results"](statement_id="stmt-abc123")

        assert result["columns"] == ["id", "email"]
        assert result["rows"] == [[1, "alice@example.com"], [2, "bob@example.com"]]
        assert result["total_rows"] == 2


class TestRedshiftListDatabases:
    def test_missing_cluster(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["redshift_list_databases"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {"Databases": ["dev", "staging", "analytics"], "NextToken": ""}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.redshift_tool.redshift_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["redshift_list_databases"](cluster_identifier="my-cluster")

        assert result["count"] == 3
        assert "dev" in result["databases"]


class TestRedshiftListTables:
    def test_missing_database(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["redshift_list_tables"](database="", cluster_identifier="my-cluster")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {
            "Tables": [
                {"name": "users", "schema": "public", "type": "TABLE"},
                {"name": "orders", "schema": "public", "type": "TABLE"},
            ],
            "NextToken": "",
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.redshift_tool.redshift_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["redshift_list_tables"](database="dev", cluster_identifier="my-cluster")

        assert result["count"] == 2
        assert result["tables"][0]["name"] == "users"
