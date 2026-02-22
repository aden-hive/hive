"""
Tests for Databricks tool.

Tests cover:
- Query execution with mocked Databricks client
- Read-only enforcement (blocking write operations)
- Row limiting
- Table description
- Error handling and user-friendly messages
- Credential resolution
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.credentials import CredentialStoreAdapter
from aden_tools.tools.databricks_tool import register_tools


@pytest.fixture
def mcp():
    """Create a FastMCP instance for testing."""
    return FastMCP("test-server")


@pytest.fixture
def mock_credentials():
    """Create mock credentials for testing."""
    return CredentialStoreAdapter.for_testing(
        {
            "databricks": "dapi-test-token-12345",
            "databricks_host": "adb-12345.6.azuredatabricks.net",
        }
    )


@pytest.fixture
def registered_mcp(mcp, mock_credentials):
    """Register Databricks tools with mock credentials."""
    register_tools(mcp, credentials=mock_credentials)
    return mcp


class TestReadOnlyEnforcement:
    """Tests for SQL write operation blocking."""

    def test_blocks_insert(self, registered_mcp):
        """INSERT statements should be blocked."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]
        result = tool.fn(sql="INSERT INTO table VALUES (1, 2)")
        assert "error" in result
        assert "Write operations are not allowed" in result["error"]

    def test_blocks_update(self, registered_mcp):
        """UPDATE statements should be blocked."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]
        result = tool.fn(sql="UPDATE table SET col = 1")
        assert "error" in result
        assert "Write operations are not allowed" in result["error"]

    def test_blocks_delete(self, registered_mcp):
        """DELETE statements should be blocked."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]
        result = tool.fn(sql="DELETE FROM table WHERE id = 1")
        assert "error" in result
        assert "Write operations are not allowed" in result["error"]

    def test_blocks_drop(self, registered_mcp):
        """DROP statements should be blocked."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]
        result = tool.fn(sql="DROP TABLE my_table")
        assert "error" in result
        assert "Write operations are not allowed" in result["error"]

    def test_blocks_create(self, registered_mcp):
        """CREATE statements should be blocked."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]
        result = tool.fn(sql="CREATE TABLE my_table (id INT)")
        assert "error" in result
        assert "Write operations are not allowed" in result["error"]

    def test_blocks_alter(self, registered_mcp):
        """ALTER statements should be blocked."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]
        result = tool.fn(sql="ALTER TABLE my_table ADD COLUMN new_col INT")
        assert "error" in result
        assert "Write operations are not allowed" in result["error"]

    def test_blocks_truncate(self, registered_mcp):
        """TRUNCATE statements should be blocked."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]
        result = tool.fn(sql="TRUNCATE TABLE my_table")
        assert "error" in result
        assert "Write operations are not allowed" in result["error"]

    def test_blocks_merge(self, registered_mcp):
        """MERGE statements should be blocked."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]
        result = tool.fn(sql="MERGE INTO target USING source ON condition WHEN MATCHED THEN UPDATE")
        assert "error" in result
        assert "Write operations are not allowed" in result["error"]

    def test_blocks_case_insensitive(self, registered_mcp):
        """Write detection should be case-insensitive."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]
        result = tool.fn(sql="insert into table values (1)")
        assert "error" in result
        assert "Write operations are not allowed" in result["error"]

    def test_allows_select(self, registered_mcp):
        """SELECT statements should be allowed (will fail on client, not validation)."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]
        with patch(
            "aden_tools.tools.databricks_tool.databricks_tool._create_databricks_client"
        ) as mock_create_client:
            mock_create_client.side_effect = Exception("Mock error")
            result = tool.fn(sql="SELECT * FROM table")
            # Should not have the write operation error
            assert "Write operations are not allowed" not in result.get("error", "")

    def test_allows_select_with_subquery(self, registered_mcp):
        """Complex SELECT with subqueries should be allowed."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]
        with patch(
            "aden_tools.tools.databricks_tool.databricks_tool._create_databricks_client"
        ) as mock_create_client:
            mock_create_client.side_effect = Exception("Mock error")
            result = tool.fn(
                sql="""
                SELECT a.*, b.count
                FROM (SELECT id, name FROM users) a
                JOIN (SELECT user_id, COUNT(*) as count FROM orders GROUP BY user_id) b
                ON a.id = b.user_id
            """
            )
            assert "Write operations are not allowed" not in result.get("error", "")


class TestRowLimits:
    """Tests for row limit validation."""

    def test_rejects_zero_max_rows(self, registered_mcp):
        """max_rows of 0 should be rejected."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]
        result = tool.fn(sql="SELECT 1", max_rows=0)
        assert "error" in result
        assert "max_rows must be at least 1" in result["error"]

    def test_rejects_negative_max_rows(self, registered_mcp):
        """Negative max_rows should be rejected."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]
        result = tool.fn(sql="SELECT 1", max_rows=-1)
        assert "error" in result
        assert "max_rows must be at least 1" in result["error"]

    def test_rejects_excessive_max_rows(self, registered_mcp):
        """max_rows over 10000 should be rejected."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]
        result = tool.fn(sql="SELECT 1", max_rows=10001)
        assert "error" in result
        assert "max_rows cannot exceed 10000" in result["error"]

    def test_accepts_valid_max_rows(self, registered_mcp):
        """Valid max_rows values should be accepted."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]
        with patch(
            "aden_tools.tools.databricks_tool.databricks_tool._create_databricks_client"
        ) as mock_create_client:
            mock_create_client.side_effect = Exception("Mock error")
            # These should pass validation (will fail on mock client)
            for max_rows in [1, 100, 1000, 10000]:
                result = tool.fn(sql="SELECT 1", max_rows=max_rows)
                assert "max_rows" not in result.get("error", "")


class TestQueryExecution:
    """Tests for successful query execution."""

    def test_successful_query(self, registered_mcp):
        """Test successful query execution with mocked client."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_tool._create_databricks_client"
        ) as mock_create_client:
            # Set up mock client
            mock_client = MagicMock()
            mock_create_client.return_value = mock_client

            # Mock response
            mock_response = MagicMock()

            # Mock status
            mock_response.status.state.value = "SUCCEEDED"

            # Mock schema
            mock_col1 = MagicMock()
            mock_col1.name = "id"
            mock_col1.type_text = "BIGINT"
            mock_col2 = MagicMock()
            mock_col2.name = "name"
            mock_col2.type_text = "STRING"
            mock_response.manifest.schema.columns = [mock_col1, mock_col2]

            # Mock data
            mock_response.result.data_array = [
                ["1", "Alice"],
                ["2", "Bob"],
            ]

            mock_client.statement_execution.execute_statement.return_value = mock_response

            result = tool.fn(sql="SELECT id, name FROM users")

            assert result["success"] is True
            assert len(result["rows"]) == 2
            assert result["rows"][0] == {"id": "1", "name": "Alice"}
            assert result["rows"][1] == {"id": "2", "name": "Bob"}
            assert result["total_rows"] == 2
            assert result["query_truncated"] is False
            assert len(result["schema"]) == 2

    def test_query_truncation(self, registered_mcp):
        """Test that results are truncated when exceeding max_rows."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_tool._create_databricks_client"
        ) as mock_create_client:
            mock_client = MagicMock()
            mock_create_client.return_value = mock_client

            mock_response = MagicMock()
            mock_response.status.state.value = "SUCCEEDED"

            mock_col = MagicMock()
            mock_col.name = "id"
            mock_col.type_text = "BIGINT"
            mock_response.manifest.schema.columns = [mock_col]

            # Create 10 rows of data
            mock_response.result.data_array = [[str(i)] for i in range(10)]

            mock_client.statement_execution.execute_statement.return_value = mock_response

            # Request only 5 rows
            result = tool.fn(sql="SELECT id FROM users", max_rows=5)

            assert result["success"] is True
            assert result["total_rows"] == 5
            assert result["query_truncated"] is True
            assert len(result["rows"]) == 5


class TestDescribeTable:
    """Tests for describe_databricks_table tool."""

    def test_empty_table_name(self, registered_mcp):
        """Empty table_name should be rejected."""
        tool = registered_mcp._tool_manager._tools["describe_databricks_table"]
        result = tool.fn(table_name="")
        assert "error" in result
        assert "table_name is required" in result["error"]

    def test_whitespace_table_name(self, registered_mcp):
        """Whitespace-only table_name should be rejected."""
        tool = registered_mcp._tool_manager._tools["describe_databricks_table"]
        result = tool.fn(table_name="   ")
        assert "error" in result
        assert "table_name is required" in result["error"]

    def test_invalid_format(self, registered_mcp):
        """Table name without full qualification should be rejected."""
        tool = registered_mcp._tool_manager._tools["describe_databricks_table"]
        result = tool.fn(table_name="just_a_table")
        assert "error" in result
        assert "catalog.schema.table" in result["error"]

    def test_two_part_name(self, registered_mcp):
        """Two-part table name should be rejected."""
        tool = registered_mcp._tool_manager._tools["describe_databricks_table"]
        result = tool.fn(table_name="schema.table")
        assert "error" in result
        assert "catalog.schema.table" in result["error"]

    def test_successful_describe(self, registered_mcp):
        """Test successful table description with mocked client."""
        tool = registered_mcp._tool_manager._tools["describe_databricks_table"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_tool._create_databricks_client"
        ) as mock_create_client:
            mock_client = MagicMock()
            mock_create_client.return_value = mock_client

            # Mock table info
            mock_table_info = MagicMock()
            mock_col1 = MagicMock()
            mock_col1.name = "id"
            mock_col1.type_text = "BIGINT"
            mock_col1.comment = "Primary key"
            mock_col2 = MagicMock()
            mock_col2.name = "email"
            mock_col2.type_text = "STRING"
            mock_col2.comment = None
            mock_table_info.columns = [mock_col1, mock_col2]
            mock_client.tables.get.return_value = mock_table_info

            result = tool.fn(table_name="main.default.users")

            assert result["success"] is True
            assert result["table_name"] == "main.default.users"
            assert len(result["columns"]) == 2
            assert result["columns"][0]["name"] == "id"
            assert result["columns"][0]["type"] == "BIGINT"
            assert result["columns"][0]["comment"] == "Primary key"
            assert result["columns"][1]["name"] == "email"
            assert result["columns"][1]["comment"] is None


class TestErrorHandling:
    """Tests for error handling and user-friendly messages."""

    def test_authentication_error(self, registered_mcp):
        """Authentication errors should provide helpful messages."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_tool._create_databricks_client"
        ) as mock_create_client:
            mock_create_client.side_effect = Exception("401 Unauthorized")
            result = tool.fn(sql="SELECT 1")

            assert "error" in result
            assert "authentication failed" in result["error"].lower()
            assert "help" in result
            assert "DATABRICKS_TOKEN" in result["help"]

    def test_permission_error(self, registered_mcp):
        """Permission errors should provide helpful messages."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_tool._create_databricks_client"
        ) as mock_create_client:
            mock_create_client.side_effect = Exception(
                "403 Permission denied for table main.default.users"
            )
            result = tool.fn(sql="SELECT 1")

            assert "error" in result
            assert "permission denied" in result["error"].lower()
            assert "help" in result

    def test_not_found_error(self, registered_mcp):
        """Not found errors should provide helpful messages."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_tool._create_databricks_client"
        ) as mock_create_client:
            mock_create_client.side_effect = Exception(
                "404 Not found: Table main.default.nonexistent"
            )
            result = tool.fn(sql="SELECT 1")

            assert "error" in result
            assert "not found" in result["error"].lower()
            assert "help" in result

    def test_table_not_found_error(self, registered_mcp):
        """Table not found errors should provide helpful messages."""
        tool = registered_mcp._tool_manager._tools["describe_databricks_table"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_tool._create_databricks_client"
        ) as mock_create_client:
            mock_create_client.side_effect = Exception(
                "404 Not found: Table main.default.nonexistent"
            )
            result = tool.fn(table_name="main.default.nonexistent")

            assert "error" in result
            assert "not found" in result["error"].lower()

    def test_missing_token(self, mcp):
        """Missing DATABRICKS_TOKEN should provide clear error."""
        mock_creds = CredentialStoreAdapter.for_testing(
            {
                "databricks_host": "adb-12345.6.azuredatabricks.net",
            }
        )
        register_tools(mcp, credentials=mock_creds)
        tool = mcp._tool_manager._tools["run_databricks_sql"]
        result = tool.fn(sql="SELECT 1")

        assert "error" in result
        assert "DATABRICKS_TOKEN" in result["error"]

    def test_missing_host(self, mcp):
        """Missing DATABRICKS_HOST should provide clear error."""
        mock_creds = CredentialStoreAdapter.for_testing(
            {
                "databricks": "dapi-test-token-12345",
            }
        )
        register_tools(mcp, credentials=mock_creds)
        tool = mcp._tool_manager._tools["run_databricks_sql"]
        result = tool.fn(sql="SELECT 1")

        assert "error" in result
        assert "DATABRICKS_HOST" in result["error"]


class TestCredentialResolution:
    """Tests for credential resolution from different sources."""

    def test_uses_credential_store(self, mcp):
        """Should use credentials from CredentialStoreAdapter."""
        mock_creds = CredentialStoreAdapter.for_testing(
            {
                "databricks": "dapi-custom-token",
                "databricks_host": "custom-workspace.azuredatabricks.net",
            }
        )
        register_tools(mcp, credentials=mock_creds)

        # Verify credentials are accessible
        assert mock_creds.get("databricks") == "dapi-custom-token"
        assert mock_creds.get("databricks_host") == "custom-workspace.azuredatabricks.net"

    def test_falls_back_to_env_vars(self, mcp):
        """Should fall back to environment variables when no credential store."""
        register_tools(mcp, credentials=None)

        # Tool is registered and will use os.getenv internally
        assert "run_databricks_sql" in mcp._tool_manager._tools
        assert "describe_databricks_table" in mcp._tool_manager._tools


class TestImportError:
    """Tests for handling missing databricks-sdk package."""

    def test_import_error_message(self, registered_mcp):
        """Should provide helpful message when databricks-sdk not installed."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_tool._create_databricks_client"
        ) as mock_create_client:
            mock_create_client.side_effect = ImportError(
                "databricks-sdk is required for Databricks tools. "
                "Install it with: pip install databricks-sdk"
            )
            result = tool.fn(sql="SELECT 1")

            assert "error" in result
            assert "databricks-sdk" in result["error"]
            assert "pip install" in result["error"]
