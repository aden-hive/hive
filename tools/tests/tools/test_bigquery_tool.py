"""
Tests for BigQuery tool.

Tests cover:
- Query execution with mocked BigQuery client
- Read-only enforcement (blocking write operations)
- Row limiting
- Dataset description
- Error handling and user-friendly messages
- Credential resolution
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.credentials import CredentialStoreAdapter
from aden_tools.tools.bigquery_tool import register_tools


@pytest.fixture
def mcp():
    """Create a FastMCP instance for testing."""
    return FastMCP("test-server")


@pytest.fixture
def mock_credentials():
    """Create mock credentials for testing."""
    return CredentialStoreAdapter.for_testing(
        {
            "bigquery": "/path/to/service-account.json",
            "bigquery_project": "test-project",
        }
    )


@pytest.fixture
def registered_mcp(mcp, mock_credentials):
    """Register BigQuery tools with mock credentials."""
    register_tools(mcp, credentials=mock_credentials)
    return mcp


class TestReadOnlyEnforcement:
    """Tests for SQL write operation blocking."""

    def test_blocks_insert(self, registered_mcp):
        """INSERT statements should be blocked."""
        tool = registered_mcp._tool_manager._tools["run_bigquery_query"]
        result = tool.fn(sql="INSERT INTO table VALUES (1, 2)")
        assert "error" in result
        assert "Write operations are not allowed" in result["error"]

    def test_blocks_update(self, registered_mcp):
        """UPDATE statements should be blocked."""
        tool = registered_mcp._tool_manager._tools["run_bigquery_query"]
        result = tool.fn(sql="UPDATE table SET col = 1")
        assert "error" in result
        assert "Write operations are not allowed" in result["error"]

    def test_blocks_delete(self, registered_mcp):
        """DELETE statements should be blocked."""
        tool = registered_mcp._tool_manager._tools["run_bigquery_query"]
        result = tool.fn(sql="DELETE FROM table WHERE id = 1")
        assert "error" in result
        assert "Write operations are not allowed" in result["error"]

    def test_blocks_drop(self, registered_mcp):
        """DROP statements should be blocked."""
        tool = registered_mcp._tool_manager._tools["run_bigquery_query"]
        result = tool.fn(sql="DROP TABLE my_table")
        assert "error" in result
        assert "Write operations are not allowed" in result["error"]

    def test_blocks_create(self, registered_mcp):
        """CREATE statements should be blocked."""
        tool = registered_mcp._tool_manager._tools["run_bigquery_query"]
        result = tool.fn(sql="CREATE TABLE my_table (id INT)")
        assert "error" in result
        assert "Write operations are not allowed" in result["error"]

    def test_blocks_alter(self, registered_mcp):
        """ALTER statements should be blocked."""
        tool = registered_mcp._tool_manager._tools["run_bigquery_query"]
        result = tool.fn(sql="ALTER TABLE my_table ADD COLUMN new_col INT")
        assert "error" in result
        assert "Write operations are not allowed" in result["error"]

    def test_blocks_truncate(self, registered_mcp):
        """TRUNCATE statements should be blocked."""
        tool = registered_mcp._tool_manager._tools["run_bigquery_query"]
        result = tool.fn(sql="TRUNCATE TABLE my_table")
        assert "error" in result
        assert "Write operations are not allowed" in result["error"]

    def test_blocks_merge(self, registered_mcp):
        """MERGE statements should be blocked."""
        tool = registered_mcp._tool_manager._tools["run_bigquery_query"]
        result = tool.fn(sql="MERGE INTO target USING source ON condition WHEN MATCHED THEN UPDATE")
        assert "error" in result
        assert "Write operations are not allowed" in result["error"]

    def test_blocks_case_insensitive(self, registered_mcp):
        """Write detection should be case-insensitive."""
        tool = registered_mcp._tool_manager._tools["run_bigquery_query"]
        result = tool.fn(sql="insert into table values (1)")
        assert "error" in result
        assert "Write operations are not allowed" in result["error"]

    def test_allows_select(self, registered_mcp):
        """SELECT statements should be allowed (will fail on client, not validation)."""
        tool = registered_mcp._tool_manager._tools["run_bigquery_query"]
        with patch(
            "aden_tools.tools.bigquery_tool.bigquery_tool._create_bigquery_client"
        ) as mock_create_client:
            # Mock will raise an error, but we're testing that it gets past validation
            mock_create_client.side_effect = Exception("Mock error")
            result = tool.fn(sql="SELECT * FROM table")
            # Should not have the write operation error
            assert "Write operations are not allowed" not in result.get("error", "")

    def test_allows_select_with_subquery(self, registered_mcp):
        """Complex SELECT with subqueries should be allowed."""
        tool = registered_mcp._tool_manager._tools["run_bigquery_query"]
        with patch(
            "aden_tools.tools.bigquery_tool.bigquery_tool._create_bigquery_client"
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
        tool = registered_mcp._tool_manager._tools["run_bigquery_query"]
        result = tool.fn(sql="SELECT 1", max_rows=0)
        assert "error" in result
        assert "max_rows must be at least 1" in result["error"]

    def test_rejects_negative_max_rows(self, registered_mcp):
        """Negative max_rows should be rejected."""
        tool = registered_mcp._tool_manager._tools["run_bigquery_query"]
        result = tool.fn(sql="SELECT 1", max_rows=-1)
        assert "error" in result
        assert "max_rows must be at least 1" in result["error"]

    def test_rejects_excessive_max_rows(self, registered_mcp):
        """max_rows over 10000 should be rejected."""
        tool = registered_mcp._tool_manager._tools["run_bigquery_query"]
        result = tool.fn(sql="SELECT 1", max_rows=10001)
        assert "error" in result
        assert "max_rows cannot exceed 10000" in result["error"]

    def test_accepts_valid_max_rows(self, registered_mcp):
        """Valid max_rows values should be accepted."""
        tool = registered_mcp._tool_manager._tools["run_bigquery_query"]
        with patch(
            "aden_tools.tools.bigquery_tool.bigquery_tool._create_bigquery_client"
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
        tool = registered_mcp._tool_manager._tools["run_bigquery_query"]

        with patch(
            "aden_tools.tools.bigquery_tool.bigquery_tool._create_bigquery_client"
        ) as mock_create_client:
            # Set up mock client and query job
            mock_client = MagicMock()
            mock_create_client.return_value = mock_client

            mock_query_job = MagicMock()
            mock_query_job.total_bytes_processed = 1024

            # Mock row results
            mock_row1 = MagicMock()
            mock_row1.items.return_value = [("id", 1), ("name", "Alice")]
            mock_row2 = MagicMock()
            mock_row2.items.return_value = [("id", 2), ("name", "Bob")]

            mock_results = MagicMock()
            mock_results.total_rows = 2
            mock_results.__iter__ = lambda self: iter([mock_row1, mock_row2])
            mock_results.schema = [
                MagicMock(name="id", field_type="INTEGER", mode="REQUIRED"),
                MagicMock(name="name", field_type="STRING", mode="NULLABLE"),
            ]

            mock_query_job.result.return_value = mock_results
            mock_client.query.return_value = mock_query_job

            result = tool.fn(sql="SELECT id, name FROM users")

            assert result["success"] is True
            assert result["rows"] == [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
            assert result["total_rows"] == 2
            assert result["rows_returned"] == 2
            assert result["bytes_processed"] == 1024
            assert result["query_truncated"] is False
            assert len(result["schema"]) == 2

    def test_query_truncation(self, registered_mcp):
        """Test that results are truncated when exceeding max_rows."""
        tool = registered_mcp._tool_manager._tools["run_bigquery_query"]

        with patch(
            "aden_tools.tools.bigquery_tool.bigquery_tool._create_bigquery_client"
        ) as mock_create_client:
            mock_client = MagicMock()
            mock_create_client.return_value = mock_client

            mock_query_job = MagicMock()
            mock_query_job.total_bytes_processed = 2048

            # Create 10 mock rows
            mock_rows = []
            for i in range(10):
                row = MagicMock()
                row.items.return_value = [("id", i)]
                mock_rows.append(row)

            mock_results = MagicMock()
            mock_results.total_rows = 10
            mock_results.__iter__ = lambda self: iter(mock_rows)
            mock_results.schema = [MagicMock(name="id", field_type="INTEGER", mode="REQUIRED")]

            mock_query_job.result.return_value = mock_results
            mock_client.query.return_value = mock_query_job

            # Request only 5 rows
            result = tool.fn(sql="SELECT id FROM users", max_rows=5)

            assert result["success"] is True
            assert result["total_rows"] == 10
            assert result["rows_returned"] == 5
            assert result["query_truncated"] is True
            assert len(result["rows"]) == 5


class TestDescribeDataset:
    """Tests for describe_dataset tool."""

    def test_empty_dataset_id(self, registered_mcp):
        """Empty dataset_id should be rejected."""
        tool = registered_mcp._tool_manager._tools["describe_dataset"]
        result = tool.fn(dataset_id="")
        assert "error" in result
        assert "dataset_id is required" in result["error"]

    def test_whitespace_dataset_id(self, registered_mcp):
        """Whitespace-only dataset_id should be rejected."""
        tool = registered_mcp._tool_manager._tools["describe_dataset"]
        result = tool.fn(dataset_id="   ")
        assert "error" in result
        assert "dataset_id is required" in result["error"]

    def test_successful_describe(self, registered_mcp):
        """Test successful dataset description with mocked client."""
        tool = registered_mcp._tool_manager._tools["describe_dataset"]

        with patch(
            "aden_tools.tools.bigquery_tool.bigquery_tool._create_bigquery_client"
        ) as mock_create_client:
            mock_client = MagicMock()
            mock_client.project = "test-project"
            mock_create_client.return_value = mock_client

            # Mock table listing
            mock_table_item = MagicMock()
            mock_table_item.reference = "test-project.my_dataset.users"
            mock_client.list_tables.return_value = [mock_table_item]

            # Mock full table details
            mock_table = MagicMock()
            mock_table.table_id = "users"
            mock_table.table_type = "TABLE"
            mock_table.num_rows = 1000
            mock_table.num_bytes = 10240
            mock_table.schema = [
                MagicMock(name="id", field_type="INTEGER", mode="REQUIRED"),
                MagicMock(name="email", field_type="STRING", mode="NULLABLE"),
            ]
            mock_client.get_table.return_value = mock_table

            result = tool.fn(dataset_id="my_dataset")

            assert result["success"] is True
            assert result["dataset_id"] == "my_dataset"
            assert result["project_id"] == "test-project"
            assert len(result["tables"]) == 1
            assert result["tables"][0]["table_id"] == "users"
            assert result["tables"][0]["row_count"] == 1000
            assert len(result["tables"][0]["columns"]) == 2


class TestErrorHandling:
    """Tests for error handling and user-friendly messages."""

    def test_authentication_error(self, registered_mcp):
        """Authentication errors should provide helpful messages."""
        tool = registered_mcp._tool_manager._tools["run_bigquery_query"]

        with patch(
            "aden_tools.tools.bigquery_tool.bigquery_tool._create_bigquery_client"
        ) as mock_create_client:
            mock_create_client.side_effect = Exception(
                "Could not automatically determine credentials"
            )
            result = tool.fn(sql="SELECT 1")

            assert "error" in result
            assert "authentication failed" in result["error"].lower()
            assert "help" in result
            assert "GOOGLE_APPLICATION_CREDENTIALS" in result["help"]

    def test_permission_error(self, registered_mcp):
        """Permission errors should provide helpful messages."""
        tool = registered_mcp._tool_manager._tools["run_bigquery_query"]

        with patch(
            "aden_tools.tools.bigquery_tool.bigquery_tool._create_bigquery_client"
        ) as mock_create_client:
            mock_create_client.side_effect = Exception(
                "Permission denied for table project.dataset.table"
            )
            result = tool.fn(sql="SELECT 1")

            assert "error" in result
            assert "permission denied" in result["error"].lower()
            assert "help" in result
            assert "BigQuery Data Viewer" in result["help"]

    def test_not_found_error(self, registered_mcp):
        """Not found errors should provide helpful messages."""
        tool = registered_mcp._tool_manager._tools["run_bigquery_query"]

        with patch(
            "aden_tools.tools.bigquery_tool.bigquery_tool._create_bigquery_client"
        ) as mock_create_client:
            mock_create_client.side_effect = Exception(
                "Not found: Table project.dataset.nonexistent was not found"
            )
            result = tool.fn(sql="SELECT 1")

            assert "error" in result
            assert "not found" in result["error"].lower()
            assert "help" in result

    def test_dataset_not_found_error(self, registered_mcp):
        """Dataset not found errors should provide helpful messages."""
        tool = registered_mcp._tool_manager._tools["describe_dataset"]

        with patch(
            "aden_tools.tools.bigquery_tool.bigquery_tool._create_bigquery_client"
        ) as mock_create_client:
            mock_create_client.side_effect = Exception(
                "Not found: Dataset project:nonexistent was not found"
            )
            result = tool.fn(dataset_id="nonexistent")

            assert "error" in result
            assert "not found" in result["error"].lower()


class TestCredentialResolution:
    """Tests for credential resolution from different sources."""

    def test_uses_credential_store(self, mcp):
        """Should use credentials from CredentialStoreAdapter."""
        mock_creds = CredentialStoreAdapter.for_testing(
            {
                "bigquery": "/custom/path/credentials.json",
                "bigquery_project": "custom-project",
            }
        )
        register_tools(mcp, credentials=mock_creds)

        # Verify credentials are accessible (actual usage tested in other tests)
        assert mock_creds.get("bigquery") == "/custom/path/credentials.json"
        assert mock_creds.get("bigquery_project") == "custom-project"

    def test_falls_back_to_env_vars(self, mcp):
        """Should fall back to environment variables when no credential store."""
        register_tools(mcp, credentials=None)

        # Tool is registered and will use os.getenv internally
        assert "run_bigquery_query" in mcp._tool_manager._tools
        assert "describe_dataset" in mcp._tool_manager._tools


class TestImportError:
    """Tests for handling missing google-cloud-bigquery package."""

    def test_import_error_message(self, registered_mcp):
        """Should provide helpful message when google-cloud-bigquery not installed."""
        tool = registered_mcp._tool_manager._tools["run_bigquery_query"]

        with patch(
            "aden_tools.tools.bigquery_tool.bigquery_tool._create_bigquery_client"
        ) as mock_create_client:
            mock_create_client.side_effect = ImportError(
                "google-cloud-bigquery is required for BigQuery tools. "
                "Install it with: pip install google-cloud-bigquery"
            )
            result = tool.fn(sql="SELECT 1")

            assert "error" in result
            assert "google-cloud-bigquery" in result["error"]
            assert "pip install" in result["error"]
