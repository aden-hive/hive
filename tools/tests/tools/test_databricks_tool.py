"""Tests for Databricks tool with FastMCP."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.databricks_tool import register_tools


@pytest.fixture
def mcp():
    """Create a FastMCP instance for testing."""
    return FastMCP("test-server")


@pytest.fixture
def get_tool_fn(mcp: FastMCP):
    """Factory fixture to get any tool function by name."""
    register_tools(mcp)

    def _get(name: str):
        return mcp._tool_manager._tools[name].fn

    return _get


class TestDatabricksCredentials:
    """Tests for Databricks credential handling."""

    def test_no_credentials_returns_error(self, get_tool_fn, monkeypatch):
        """Tool without credentials returns helpful error."""
        monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
        monkeypatch.delenv("DATABRICKS_HOST", raising=False)
        fn = get_tool_fn("run_databricks_sql")

        result = fn(query="SELECT 1", warehouse_id="abc123")

        assert "error" in result
        assert "Databricks credentials not configured" in result["error"]
        assert "help" in result

    def test_no_token_returns_error(self, get_tool_fn, monkeypatch):
        """Missing token returns helpful error."""
        monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
        monkeypatch.setenv("DATABRICKS_HOST", "https://test.cloud.databricks.com")
        fn = get_tool_fn("run_databricks_sql")

        result = fn(query="SELECT 1", warehouse_id="abc123")

        assert "error" in result
        assert "Databricks credentials not configured" in result["error"]

    def test_no_host_returns_error(self, get_tool_fn, monkeypatch):
        """Missing host returns helpful error."""
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapi123")
        monkeypatch.delenv("DATABRICKS_HOST", raising=False)
        fn = get_tool_fn("run_databricks_sql")

        result = fn(query="SELECT 1", warehouse_id="abc123")

        assert "error" in result
        assert "Databricks credentials not configured" in result["error"]


class TestRunDatabricksSQL:
    """Tests for run_databricks_sql tool."""

    def test_execute_sql_success(self, get_tool_fn, monkeypatch):
        """Execute SQL returns statement_id."""
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapi123")
        monkeypatch.setenv("DATABRICKS_HOST", "https://test.cloud.databricks.com")
        fn = get_tool_fn("run_databricks_sql")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "statement_id": "stmt-123",
                "status": {"state": "PENDING"},
            }
            mock_post.return_value = mock_response

            result = fn(
                query="SELECT * FROM sales",
                warehouse_id="wh-123",
                catalog="main",
                schema="default",
            )

        assert result["success"] is True
        assert result["statement_id"] == "stmt-123"
        assert result["status"] == "PENDING"

    def test_execute_sql_error(self, get_tool_fn, monkeypatch):
        """Execute SQL error returns helpful message."""
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapi123")
        monkeypatch.setenv("DATABRICKS_HOST", "https://test.cloud.databricks.com")
        fn = get_tool_fn("run_databricks_sql")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.json.return_value = {
                "message": "Warehouse not found",
            }
            mock_post.return_value = mock_response

            result = fn(query="SELECT 1", warehouse_id="invalid-wh")

        assert "error" in result
        assert "400" in result["error"]


class TestDatabricksGetStatementStatus:
    """Tests for databricks_get_statement_status tool."""

    def test_get_statement_status_success(self, get_tool_fn, monkeypatch):
        """Get statement status returns status."""
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapi123")
        monkeypatch.setenv("DATABRICKS_HOST", "https://test.cloud.databricks.com")
        fn = get_tool_fn("databricks_get_statement_status")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "statement_id": "stmt-123",
                "status": {"state": "SUCCEEDED"},
                "result": {
                    "data": [[1, "Alice"], [2, "Bob"]],
                    "schema": {"columns": [{"name": "id"}, {"name": "name"}]},
                },
            }
            mock_get.return_value = mock_response

            result = fn(statement_id="stmt-123")

        assert result["success"] is True
        assert result["state"] == "SUCCEEDED"
        assert "result" in result

    def test_get_statement_status_failed(self, get_tool_fn, monkeypatch):
        """Get statement status for failed statement."""
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapi123")
        monkeypatch.setenv("DATABRICKS_HOST", "https://test.cloud.databricks.com")
        fn = get_tool_fn("databricks_get_statement_status")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "statement_id": "stmt-123",
                "status": {
                    "state": "FAILED",
                    "error": {"message": "Table not found"},
                },
            }
            mock_get.return_value = mock_response

            result = fn(statement_id="stmt-123")

        assert result["success"] is True
        assert result["state"] == "FAILED"
        assert result["error"]["message"] == "Table not found"


class TestTriggerDatabricksJob:
    """Tests for trigger_databricks_job tool."""

    def test_trigger_job_success(self, get_tool_fn, monkeypatch):
        """Trigger job returns run_id."""
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapi123")
        monkeypatch.setenv("DATABRICKS_HOST", "https://test.cloud.databricks.com")
        fn = get_tool_fn("trigger_databricks_job")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "run_id": 12345,
                "number_in_job": 1,
            }
            mock_post.return_value = mock_response

            result = fn(job_id=100, parameters={"param1": "value1"})

        assert result["success"] is True
        assert result["run_id"] == 12345
        assert result["number_in_job"] == 1

    def test_trigger_job_error(self, get_tool_fn, monkeypatch):
        """Trigger job error returns helpful message."""
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapi123")
        monkeypatch.setenv("DATABRICKS_HOST", "https://test.cloud.databricks.com")
        fn = get_tool_fn("trigger_databricks_job")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 400
            mock_response.json.return_value = {
                "message": "Job not found",
            }
            mock_post.return_value = mock_response

            result = fn(job_id=999)

        assert "error" in result
        assert "400" in result["error"]


class TestDatabricksGetJobStatus:
    """Tests for databricks_get_job_status tool."""

    def test_get_job_status_success(self, get_tool_fn, monkeypatch):
        """Get job status returns status."""
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapi123")
        monkeypatch.setenv("DATABRICKS_HOST", "https://test.cloud.databricks.com")
        fn = get_tool_fn("databricks_get_job_status")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "run_id": 12345,
                "state": {
                    "life_cycle_state": "RUNNING",
                    "result_state": None,
                    "state_message": "Job is running",
                },
                "start_time": 1234567890,
                "run_page_url": "https://test.cloud.databricks.com/jobs/12345",
            }
            mock_get.return_value = mock_response

            result = fn(run_id=12345)

        assert result["success"] is True
        assert result["state"] == "RUNNING"
        assert result["run_page_url"] == "https://test.cloud.databricks.com/jobs/12345"

    def test_get_job_status_completed(self, get_tool_fn, monkeypatch):
        """Get job status for completed job."""
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapi123")
        monkeypatch.setenv("DATABRICKS_HOST", "https://test.cloud.databricks.com")
        fn = get_tool_fn("databricks_get_job_status")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "run_id": 12345,
                "state": {
                    "life_cycle_state": "TERMINATED",
                    "result_state": "SUCCESS",
                    "state_message": "Job completed successfully",
                },
                "start_time": 1234567890,
                "end_time": 1234567999,
                "run_duration": 109000,
            }
            mock_get.return_value = mock_response

            result = fn(run_id=12345)

        assert result["success"] is True
        assert result["state"] == "TERMINATED"
        assert result["result_state"] == "SUCCESS"


class TestDescribeTable:
    """Tests for describe_table tool."""

    def test_describe_table_success(self, get_tool_fn, monkeypatch):
        """Describe table returns table schema."""
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapi123")
        monkeypatch.setenv("DATABRICKS_HOST", "https://test.cloud.databricks.com")
        fn = get_tool_fn("describe_table")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "name": "sales",
                "full_name": "main.default.sales",
                "catalog_name": "main",
                "schema_name": "default",
                "table_type": "MANAGED",
                "data_source_format": "DELTA",
                "comment": "Sales transactions table",
                "owner": "admin",
                "columns": [
                    {
                        "name": "id",
                        "type_text": "BIGINT",
                        "nullable": False,
                        "comment": "Primary key",
                    },
                    {
                        "name": "amount",
                        "type_text": "DOUBLE",
                        "nullable": True,
                        "comment": "Sale amount",
                    },
                    {
                        "name": "date",
                        "type_text": "DATE",
                        "nullable": True,
                        "comment": "Transaction date",
                    },
                ],
            }
            mock_get.return_value = mock_response

            result = fn(full_name="main.default.sales")

        assert result["success"] is True
        assert result["full_name"] == "main.default.sales"
        assert result["table_type"] == "MANAGED"
        assert len(result["columns"]) == 3
        assert result["columns"][0]["name"] == "id"
        assert result["columns"][0]["type_text"] == "BIGINT"

    def test_describe_table_not_found(self, get_tool_fn, monkeypatch):
        """Describe table error for non-existent table."""
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapi123")
        monkeypatch.setenv("DATABRICKS_HOST", "https://test.cloud.databricks.com")
        fn = get_tool_fn("describe_table")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.json.return_value = {
                "message": "Table not found",
            }
            mock_get.return_value = mock_response

            result = fn(full_name="main.nonexistent.table")

        assert "error" in result


class TestListWorkspace:
    """Tests for list_workspace tool."""

    def test_list_workspace_success(self, get_tool_fn, monkeypatch):
        """List workspace returns objects."""
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapi123")
        monkeypatch.setenv("DATABRICKS_HOST", "https://test.cloud.databricks.com")
        fn = get_tool_fn("list_workspace")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "objects": [
                    {
                        "path": "/Users/user@company.com/notebook1",
                        "object_type": "NOTEBOOK",
                        "object_id": 123,
                    },
                    {
                        "path": "/Users/user@company.com/folder1",
                        "object_type": "DIRECTORY",
                        "object_id": 456,
                    },
                    {
                        "path": "/Users/user@company.com/file1.py",
                        "object_type": "FILE",
                        "object_id": 789,
                    },
                ],
            }
            mock_get.return_value = mock_response

            result = fn(path="/Users/user@company.com")

        assert result["success"] is True
        assert result["count"] == 3
        assert result["objects"][0]["object_type"] == "NOTEBOOK"

    def test_list_workspace_root(self, get_tool_fn, monkeypatch):
        """List workspace root returns objects."""
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapi123")
        monkeypatch.setenv("DATABRICKS_HOST", "https://test.cloud.databricks.com")
        fn = get_tool_fn("list_workspace")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "objects": [
                    {"path": "/Shared", "object_type": "DIRECTORY", "object_id": 1},
                    {"path": "/Users", "object_type": "DIRECTORY", "object_id": 2},
                ],
            }
            mock_get.return_value = mock_response

            result = fn()

        assert result["success"] is True
        assert result["path"] == "/"


class TestDatabricksListWarehouses:
    """Tests for databricks_list_warehouses tool."""

    def test_list_warehouses_success(self, get_tool_fn, monkeypatch):
        """List warehouses returns warehouses."""
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapi123")
        monkeypatch.setenv("DATABRICKS_HOST", "https://test.cloud.databricks.com")
        fn = get_tool_fn("databricks_list_warehouses")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "warehouses": [
                    {
                        "id": "wh-123",
                        "name": "Starter Warehouse",
                        "size": "2X-Small",
                        "state": "RUNNING",
                        "auto_stop_mins": 10,
                    },
                    {
                        "id": "wh-456",
                        "name": "Production Warehouse",
                        "size": "Small",
                        "state": "STOPPED",
                        "auto_stop_mins": 5,
                    },
                ],
            }
            mock_get.return_value = mock_response

            result = fn()

        assert result["success"] is True
        assert result["count"] == 2
        assert result["warehouses"][0]["name"] == "Starter Warehouse"
        assert result["warehouses"][0]["state"] == "RUNNING"


class TestDatabricksListCatalogs:
    """Tests for databricks_list_catalogs tool."""

    def test_list_catalogs_success(self, get_tool_fn, monkeypatch):
        """List catalogs returns catalogs."""
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapi123")
        monkeypatch.setenv("DATABRICKS_HOST", "https://test.cloud.databricks.com")
        fn = get_tool_fn("databricks_list_catalogs")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "catalogs": [
                    {"name": "main", "comment": "Main catalog", "owner": "admin"},
                    {"name": "dev", "comment": "Development catalog", "owner": "dev_team"},
                ],
            }
            mock_get.return_value = mock_response

            result = fn()

        assert result["success"] is True
        assert result["count"] == 2
        assert result["catalogs"][0]["name"] == "main"


class TestDatabricksListSchemas:
    """Tests for databricks_list_schemas tool."""

    def test_list_schemas_success(self, get_tool_fn, monkeypatch):
        """List schemas returns schemas."""
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapi123")
        monkeypatch.setenv("DATABRICKS_HOST", "https://test.cloud.databricks.com")
        fn = get_tool_fn("databricks_list_schemas")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "schemas": [
                    {"name": "default", "full_name": "main.default", "comment": "Default schema"},
                    {
                        "name": "analytics",
                        "full_name": "main.analytics",
                        "comment": "Analytics data",
                    },
                ],
            }
            mock_get.return_value = mock_response

            result = fn(catalog_name="main")

        assert result["success"] is True
        assert result["catalog_name"] == "main"
        assert result["count"] == 2
        assert result["schemas"][0]["name"] == "default"


class TestDatabricksListTables:
    """Tests for databricks_list_tables tool."""

    def test_list_tables_success(self, get_tool_fn, monkeypatch):
        """List tables returns tables."""
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapi123")
        monkeypatch.setenv("DATABRICKS_HOST", "https://test.cloud.databricks.com")
        fn = get_tool_fn("databricks_list_tables")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "tables": [
                    {
                        "name": "sales",
                        "full_name": "main.default.sales",
                        "table_type": "MANAGED",
                        "data_source_format": "DELTA",
                    },
                    {
                        "name": "customers",
                        "full_name": "main.default.customers",
                        "table_type": "EXTERNAL",
                        "data_source_format": "DELTA",
                    },
                ],
            }
            mock_get.return_value = mock_response

            result = fn(catalog_name="main", schema_name="default")

        assert result["success"] is True
        assert result["catalog_name"] == "main"
        assert result["schema_name"] == "default"
        assert result["count"] == 2
        assert result["tables"][0]["name"] == "sales"


class TestDatabricksListJobs:
    """Tests for databricks_list_jobs tool."""

    def test_list_jobs_success(self, get_tool_fn, monkeypatch):
        """List jobs returns jobs."""
        monkeypatch.setenv("DATABRICKS_TOKEN", "dapi123")
        monkeypatch.setenv("DATABRICKS_HOST", "https://test.cloud.databricks.com")
        fn = get_tool_fn("databricks_list_jobs")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "jobs": [
                    {
                        "job_id": 100,
                        "settings": {"name": "Daily ETL"},
                        "created_time": 1234567890,
                    },
                    {
                        "job_id": 200,
                        "settings": {"name": "Weekly Report"},
                        "created_time": 1234567900,
                    },
                ],
                "has_more": False,
            }
            mock_get.return_value = mock_response

            result = fn(limit=20)

        assert result["success"] is True
        assert result["count"] == 2
        assert result["has_more"] is False
        assert result["jobs"][0]["job_id"] == 100
