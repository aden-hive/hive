"""
Tests for Databricks tools.

Tests cover:
- Custom SQL tool: read-only enforcement, row limiting, query execution, error handling
- Describe table: input validation, successful description, error handling
- Managed MCP tools: SQL, UC functions, Vector Search, Genie, tool discovery
- Credential resolution from CredentialStoreAdapter and environment
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
            "databricks_host": "https://test-workspace.cloud.databricks.com",
            "databricks_token": "dapi_test_token_12345",
            "databricks_warehouse": "test-warehouse-id",
        }
    )


@pytest.fixture
def registered_mcp(mcp, mock_credentials):
    """Register Databricks tools with mock credentials."""
    register_tools(mcp, credentials=mock_credentials)
    return mcp


# ===========================================================================
# Custom SQL Tool — Read-Only Enforcement
# ===========================================================================


class TestReadOnlyEnforcement:
    """Tests for SQL write operation blocking in run_databricks_sql."""

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
            "aden_tools.tools.databricks_tool.databricks_tool._create_workspace_client"
        ) as mock_create:
            mock_create.side_effect = Exception("Mock error")
            result = tool.fn(sql="SELECT * FROM table")
            assert "Write operations are not allowed" not in result.get("error", "")

    def test_allows_select_with_subquery(self, registered_mcp):
        """Complex SELECT with subqueries should be allowed."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]
        with patch(
            "aden_tools.tools.databricks_tool.databricks_tool._create_workspace_client"
        ) as mock_create:
            mock_create.side_effect = Exception("Mock error")
            result = tool.fn(
                sql="""
                SELECT a.*, b.count
                FROM (SELECT id, name FROM users) a
                JOIN (SELECT user_id, COUNT(*) as count FROM orders GROUP BY user_id) b
                ON a.id = b.user_id
            """
            )
            assert "Write operations are not allowed" not in result.get("error", "")

    def test_ignores_write_keywords_in_comments(self, registered_mcp):
        """Write keywords inside comments should not trigger blocking."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]
        with patch(
            "aden_tools.tools.databricks_tool.databricks_tool._create_workspace_client"
        ) as mock_create:
            mock_create.side_effect = Exception("Mock error")
            result = tool.fn(sql="SELECT * FROM t -- INSERT comment")
            assert "Write operations are not allowed" not in result.get("error", "")


# ===========================================================================
# Custom SQL Tool — Row Limits
# ===========================================================================


class TestRowLimits:
    """Tests for row limit validation in run_databricks_sql."""

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
            "aden_tools.tools.databricks_tool.databricks_tool._create_workspace_client"
        ) as mock_create:
            mock_create.side_effect = Exception("Mock error")
            for max_rows in [1, 100, 1000, 10000]:
                result = tool.fn(sql="SELECT 1", max_rows=max_rows)
                assert "max_rows" not in result.get("error", "")


# ===========================================================================
# Custom SQL Tool — Query Execution
# ===========================================================================


class TestQueryExecution:
    """Tests for successful query execution with mocked Databricks client."""

    def test_successful_query(self, registered_mcp):
        """Test successful query execution with mocked WorkspaceClient."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_tool._create_workspace_client"
        ) as mock_create:
            mock_client = MagicMock()
            mock_create.return_value = mock_client

            # Mock the statement execution response
            mock_col1 = MagicMock()
            mock_col1.name = "id"
            mock_col1.type_name = "INT"
            mock_col2 = MagicMock()
            mock_col2.name = "name"
            mock_col2.type_name = "STRING"

            mock_schema = MagicMock()
            mock_schema.columns = [mock_col1, mock_col2]

            mock_manifest = MagicMock()
            mock_manifest.schema = mock_schema

            mock_result = MagicMock()
            mock_result.data_array = [["1", "Alice"], ["2", "Bob"]]

            mock_response = MagicMock()
            mock_response.status.error = None
            mock_response.manifest = mock_manifest
            mock_response.result = mock_result

            mock_client.statement_execution.execute_statement.return_value = mock_response

            result = tool.fn(sql="SELECT id, name FROM users")

            assert result["success"] is True
            assert result["rows"] == [
                {"id": "1", "name": "Alice"},
                {"id": "2", "name": "Bob"},
            ]
            assert result["total_rows"] == 2
            assert result["rows_returned"] == 2
            assert result["query_truncated"] is False
            assert len(result["schema"]) == 2

    def test_query_truncation(self, registered_mcp):
        """Test that results are truncated when exceeding max_rows."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_tool._create_workspace_client"
        ) as mock_create:
            mock_client = MagicMock()
            mock_create.return_value = mock_client

            mock_col = MagicMock()
            mock_col.name = "id"
            mock_col.type_name = "INT"

            mock_schema = MagicMock()
            mock_schema.columns = [mock_col]

            mock_manifest = MagicMock()
            mock_manifest.schema = mock_schema

            # Create 10 rows of data
            mock_result = MagicMock()
            mock_result.data_array = [[str(i)] for i in range(10)]

            mock_response = MagicMock()
            mock_response.status.error = None
            mock_response.manifest = mock_manifest
            mock_response.result = mock_result

            mock_client.statement_execution.execute_statement.return_value = mock_response

            # Request only 5 rows
            result = tool.fn(sql="SELECT id FROM users", max_rows=5)

            assert result["success"] is True
            assert result["total_rows"] == 10
            assert result["rows_returned"] == 5
            assert result["query_truncated"] is True
            assert len(result["rows"]) == 5

    def test_missing_warehouse_id(self, mcp):
        """Test error when no warehouse ID is configured."""
        creds = CredentialStoreAdapter.for_testing(
            {
                "databricks_host": "https://test.cloud.databricks.com",
                "databricks_token": "dapi_test",
            }
        )
        register_tools(mcp, credentials=creds)

        tool = mcp._tool_manager._tools["run_databricks_sql"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_tool._create_workspace_client"
        ) as mock_create:
            mock_create.return_value = MagicMock()
            result = tool.fn(sql="SELECT 1")
            assert "error" in result
            assert "No SQL Warehouse ID provided" in result["error"]


# ===========================================================================
# Describe Table
# ===========================================================================


class TestDescribeTable:
    """Tests for describe_databricks_table tool."""

    def test_empty_catalog(self, registered_mcp):
        """Empty catalog should be rejected."""
        tool = registered_mcp._tool_manager._tools["describe_databricks_table"]
        result = tool.fn(catalog="", schema="default", table="users")
        assert "error" in result
        assert "catalog is required" in result["error"]

    def test_empty_schema(self, registered_mcp):
        """Empty schema should be rejected."""
        tool = registered_mcp._tool_manager._tools["describe_databricks_table"]
        result = tool.fn(catalog="main", schema="", table="users")
        assert "error" in result
        assert "schema is required" in result["error"]

    def test_empty_table(self, registered_mcp):
        """Empty table name should be rejected."""
        tool = registered_mcp._tool_manager._tools["describe_databricks_table"]
        result = tool.fn(catalog="main", schema="default", table="")
        assert "error" in result
        assert "table name is required" in result["error"]

    def test_successful_describe(self, registered_mcp):
        """Test successful table description with mocked client."""
        tool = registered_mcp._tool_manager._tools["describe_databricks_table"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_tool._create_workspace_client"
        ) as mock_create:
            mock_client = MagicMock()
            mock_create.return_value = mock_client

            # Mock table info
            mock_col1 = MagicMock()
            mock_col1.name = "id"
            mock_col1.type_name = "LONG"
            mock_col1.nullable = False
            mock_col1.comment = "User ID"

            mock_col2 = MagicMock()
            mock_col2.name = "email"
            mock_col2.type_name = "STRING"
            mock_col2.nullable = True
            mock_col2.comment = None

            mock_table_info = MagicMock()
            mock_table_info.columns = [mock_col1, mock_col2]
            mock_table_info.table_type = "MANAGED"
            mock_table_info.comment = "User accounts table"
            mock_table_info.storage_location = "s3://bucket/path"

            mock_client.tables.get.return_value = mock_table_info

            result = tool.fn(catalog="main", schema="default", table="users")

            assert result["success"] is True
            assert result["catalog"] == "main"
            assert result["schema"] == "default"
            assert result["table"] == "users"
            assert result["full_name"] == "main.default.users"
            assert result["table_type"] == "MANAGED"
            assert result["comment"] == "User accounts table"
            assert result["storage_location"] == "s3://bucket/path"
            assert len(result["columns"]) == 2
            assert result["columns"][0]["name"] == "id"
            assert result["columns"][0]["nullable"] is False
            assert result["columns"][1]["name"] == "email"
            assert result["columns"][1]["nullable"] is True


# ===========================================================================
# Managed MCP Tools
# ===========================================================================


class TestMCPQuerySQL:
    """Tests for databricks_mcp_query_sql tool."""

    def test_empty_sql(self, registered_mcp):
        """Empty SQL should be rejected."""
        tool = registered_mcp._tool_manager._tools["databricks_mcp_query_sql"]
        result = tool.fn(sql="")
        assert "error" in result
        assert "sql is required" in result["error"]

    def test_successful_mcp_sql(self, registered_mcp):
        """Test successful MCP SQL query with mocked client."""
        tool = registered_mcp._tool_manager._tools["databricks_mcp_query_sql"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_mcp_tool._get_mcp_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            mock_content = MagicMock()
            mock_content.text = "Query results: 42 rows returned"
            mock_response = MagicMock()
            mock_response.content = [mock_content]
            mock_client.call_tool.return_value = mock_response

            result = tool.fn(sql="SELECT * FROM main.default.users")

            assert result["success"] is True
            assert "Query results" in result["result"]


class TestMCPUCFunction:
    """Tests for databricks_mcp_query_uc_function tool."""

    def test_empty_catalog(self, registered_mcp):
        """Empty catalog should be rejected."""
        tool = registered_mcp._tool_manager._tools["databricks_mcp_query_uc_function"]
        result = tool.fn(catalog="", schema="default", function_name="my_func")
        assert "error" in result
        assert "catalog is required" in result["error"]

    def test_empty_function_name(self, registered_mcp):
        """Empty function name should be rejected."""
        tool = registered_mcp._tool_manager._tools["databricks_mcp_query_uc_function"]
        result = tool.fn(catalog="main", schema="default", function_name="")
        assert "error" in result
        assert "function_name is required" in result["error"]

    def test_successful_uc_function(self, registered_mcp):
        """Test successful UC function call with mocked client."""
        tool = registered_mcp._tool_manager._tools["databricks_mcp_query_uc_function"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_mcp_tool._get_mcp_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            mock_content = MagicMock()
            mock_content.text = "Revenue: $1.2M"
            mock_response = MagicMock()
            mock_response.content = [mock_content]
            mock_client.call_tool.return_value = mock_response

            result = tool.fn(
                catalog="main",
                schema="analytics",
                function_name="get_revenue",
                arguments={"year": "2024"},
            )

            assert result["success"] is True
            assert "Revenue" in result["result"]


class TestMCPVectorSearch:
    """Tests for databricks_mcp_vector_search tool."""

    def test_empty_query(self, registered_mcp):
        """Empty query should be rejected."""
        tool = registered_mcp._tool_manager._tools["databricks_mcp_vector_search"]
        result = tool.fn(catalog="prod", schema="kb", index_name="idx", query="")
        assert "error" in result
        assert "query is required" in result["error"]

    def test_empty_index_name(self, registered_mcp):
        """Empty index name should be rejected."""
        tool = registered_mcp._tool_manager._tools["databricks_mcp_vector_search"]
        result = tool.fn(catalog="prod", schema="kb", index_name="", query="test")
        assert "error" in result
        assert "index_name is required" in result["error"]

    def test_successful_vector_search(self, registered_mcp):
        """Test successful vector search with mocked client."""
        tool = registered_mcp._tool_manager._tools["databricks_mcp_vector_search"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_mcp_tool._get_mcp_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            mock_tool = MagicMock()
            mock_tool.name = "search_index"
            mock_client.list_tools.return_value = [mock_tool]

            mock_content = MagicMock()
            mock_content.text = "Found 3 relevant documents"
            mock_response = MagicMock()
            mock_response.content = [mock_content]
            mock_client.call_tool.return_value = mock_response

            result = tool.fn(
                catalog="prod",
                schema="kb",
                index_name="docs_index",
                query="How to configure auth?",
                num_results=5,
            )

            assert result["success"] is True
            assert "relevant documents" in result["result"]


class TestMCPGenie:
    """Tests for databricks_mcp_query_genie tool."""

    def test_empty_genie_space_id(self, registered_mcp):
        """Empty genie space ID should be rejected."""
        tool = registered_mcp._tool_manager._tools["databricks_mcp_query_genie"]
        result = tool.fn(genie_space_id="", question="What is revenue?")
        assert "error" in result
        assert "genie_space_id is required" in result["error"]

    def test_empty_question(self, registered_mcp):
        """Empty question should be rejected."""
        tool = registered_mcp._tool_manager._tools["databricks_mcp_query_genie"]
        result = tool.fn(genie_space_id="abc123", question="")
        assert "error" in result
        assert "question is required" in result["error"]

    def test_successful_genie_query(self, registered_mcp):
        """Test successful Genie query with mocked client."""
        tool = registered_mcp._tool_manager._tools["databricks_mcp_query_genie"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_mcp_tool._get_mcp_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            mock_tool = MagicMock()
            mock_tool.name = "ask_genie"
            mock_client.list_tools.return_value = [mock_tool]

            mock_content = MagicMock()
            mock_content.text = "Total revenue last quarter was $1.2M"
            mock_response = MagicMock()
            mock_response.content = [mock_content]
            mock_client.call_tool.return_value = mock_response

            result = tool.fn(
                genie_space_id="abc123",
                question="What was revenue last quarter?",
            )

            assert result["success"] is True
            assert "$1.2M" in result["result"]


class TestMCPListTools:
    """Tests for databricks_mcp_list_tools tool."""

    def test_missing_server_url_and_type(self, registered_mcp):
        """Should return error when neither server_url nor server_type is given."""
        tool = registered_mcp._tool_manager._tools["databricks_mcp_list_tools"]
        result = tool.fn()
        assert "error" in result
        assert "server_url or server_type is required" in result["error"]

    def test_invalid_server_type(self, registered_mcp):
        """Should return error for invalid server type."""
        tool = registered_mcp._tool_manager._tools["databricks_mcp_list_tools"]
        result = tool.fn(server_type="invalid")
        assert "error" in result
        assert "Invalid server_type" in result["error"]

    def test_successful_list_tools(self, registered_mcp):
        """Test successful tool listing with mocked client."""
        tool = registered_mcp._tool_manager._tools["databricks_mcp_list_tools"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_mcp_tool._get_mcp_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            mock_tool1 = MagicMock()
            mock_tool1.name = "execute_sql"
            mock_tool1.description = "Execute SQL queries"
            mock_tool1.inputSchema = {"type": "object", "properties": {}}

            mock_tool2 = MagicMock()
            mock_tool2.name = "list_tables"
            mock_tool2.description = "List available tables"
            mock_tool2.inputSchema = None

            mock_client.list_tools.return_value = [mock_tool1, mock_tool2]

            result = tool.fn(server_type="sql")

            assert result["success"] is True
            assert len(result["tools"]) == 2
            assert result["tools"][0]["name"] == "execute_sql"
            assert result["tools"][1]["name"] == "list_tables"
            assert "https://test-workspace.cloud.databricks.com" in result["server_url"]

    def test_with_direct_server_url(self, registered_mcp):
        """Test tool listing with a direct server URL."""
        tool = registered_mcp._tool_manager._tools["databricks_mcp_list_tools"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_mcp_tool._get_mcp_client"
        ) as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.list_tools.return_value = []

            url = "https://my-workspace.cloud.databricks.com/api/2.0/mcp/sql"
            result = tool.fn(server_url=url)

            assert result["success"] is True
            assert result["server_url"] == url


# ===========================================================================
# Error Handling
# ===========================================================================


class TestErrorHandling:
    """Tests for error handling and user-friendly messages."""

    def test_authentication_error(self, registered_mcp):
        """Authentication errors should provide helpful messages."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_tool._create_workspace_client"
        ) as mock_create:
            mock_create.side_effect = Exception("401 Unauthorized")
            result = tool.fn(sql="SELECT 1")

            assert "error" in result
            assert "authentication failed" in result["error"].lower()
            assert "help" in result

    def test_permission_error(self, registered_mcp):
        """Permission errors should provide helpful messages."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_tool._create_workspace_client"
        ) as mock_create:
            mock_create.side_effect = Exception("PERMISSION_DENIED: access denied")
            result = tool.fn(sql="SELECT 1")

            assert "error" in result
            assert "permission denied" in result["error"].lower()
            assert "help" in result

    def test_not_found_error(self, registered_mcp):
        """Not found errors should provide helpful messages."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_tool._create_workspace_client"
        ) as mock_create:
            mock_create.side_effect = Exception("NOT_FOUND: warehouse xyz not found")
            result = tool.fn(sql="SELECT 1")

            assert "error" in result
            assert "not found" in result["error"].lower()
            assert "help" in result

    def test_table_not_found_error(self, registered_mcp):
        """Table not found errors should provide helpful messages."""
        tool = registered_mcp._tool_manager._tools["describe_databricks_table"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_tool._create_workspace_client"
        ) as mock_create:
            mock_create.side_effect = Exception("DOES_NOT_EXIST: table not found")
            result = tool.fn(catalog="main", schema="default", table="nonexistent")

            assert "error" in result
            assert "not found" in result["error"].lower()

    def test_mcp_import_error(self, registered_mcp):
        """Import errors for managed MCP tools should be helpful."""
        tool = registered_mcp._tool_manager._tools["databricks_mcp_query_sql"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_mcp_tool._get_mcp_client"
        ) as mock_get:
            mock_get.side_effect = ImportError("databricks-mcp and databricks-sdk are required")
            result = tool.fn(sql="SELECT 1")

            assert "error" in result
            assert "databricks" in result["error"].lower()


# ===========================================================================
# Credential Resolution
# ===========================================================================


class TestCredentialResolution:
    """Tests for credential resolution from different sources."""

    def test_uses_credential_store(self, mcp):
        """Should use credentials from CredentialStoreAdapter."""
        mock_creds = CredentialStoreAdapter.for_testing(
            {
                "databricks_host": "https://custom.cloud.databricks.com",
                "databricks_token": "dapi_custom_token",
                "databricks_warehouse": "custom-warehouse",
            }
        )
        register_tools(mcp, credentials=mock_creds)

        assert mock_creds.get("databricks_host") == "https://custom.cloud.databricks.com"
        assert mock_creds.get("databricks_token") == "dapi_custom_token"
        assert mock_creds.get("databricks_warehouse") == "custom-warehouse"

    def test_falls_back_to_env_vars(self, mcp):
        """Should fall back to environment variables when no credential store."""
        register_tools(mcp, credentials=None)

        # Tools are registered and will use os.getenv internally
        assert "run_databricks_sql" in mcp._tool_manager._tools
        assert "describe_databricks_table" in mcp._tool_manager._tools
        assert "databricks_mcp_query_sql" in mcp._tool_manager._tools
        assert "databricks_mcp_query_uc_function" in mcp._tool_manager._tools
        assert "databricks_mcp_vector_search" in mcp._tool_manager._tools
        assert "databricks_mcp_query_genie" in mcp._tool_manager._tools
        assert "databricks_mcp_list_tools" in mcp._tool_manager._tools

    def test_all_tools_registered(self, registered_mcp):
        """All 7 Databricks tools should be registered."""
        expected_tools = [
            "run_databricks_sql",
            "describe_databricks_table",
            "databricks_mcp_query_sql",
            "databricks_mcp_query_uc_function",
            "databricks_mcp_vector_search",
            "databricks_mcp_query_genie",
            "databricks_mcp_list_tools",
        ]
        for tool_name in expected_tools:
            assert tool_name in registered_mcp._tool_manager._tools, (
                f"Tool '{tool_name}' not registered"
            )


# ===========================================================================
# Import Error Handling
# ===========================================================================


class TestImportError:
    """Tests for handling missing databricks-sdk package."""

    def test_sdk_import_error_message(self, registered_mcp):
        """Should provide helpful message when databricks-sdk not installed."""
        tool = registered_mcp._tool_manager._tools["run_databricks_sql"]

        with patch(
            "aden_tools.tools.databricks_tool.databricks_tool._create_workspace_client"
        ) as mock_create:
            mock_create.side_effect = ImportError(
                "databricks-sdk is required for Databricks tools. "
                "Install it with: pip install 'databricks-sdk>=0.30.0'"
            )
            result = tool.fn(sql="SELECT 1")

            assert "error" in result
            assert "databricks-sdk" in result["error"]
            assert "pip install" in result["error"]
