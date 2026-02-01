"""Test for the Parquet tool. Goal: To test the Parquet, read and describe functions."""

from pathlib import Path
# from unittest import TestCase
from aden_tools.tools.parquet_tool.parquet_tool import register_tools
import pytest
from fastmcp import FastMCP
from unittest.mock import patch
import duckdb

# Test IDs for sandbox environment
TEST_WORKSPACE_ID = "test_workspace"
TEST_AGENT_ID = "test_agent"
TEST_SESSION_ID = "test_session"

@pytest.fixture
def mcp():
    """Fixture to create an MCP instance with Parquet tool registered."""
    mcp = FastMCP()
    register_tools(mcp)
    return mcp


@pytest.fixture
def parquet_tools(mcp: FastMCP, tmp_path: Path):
    with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
        yield {
            "parquet_info": mcp._tool_manager._tools["parquet_info"].fn,
            "parquet_preview": mcp._tool_manager._tools["parquet_preview"].fn,
            "sample_parquet": mcp._tool_manager._tools["sample_parquet"].fn,
            "run_sql_on_parquet": mcp._tool_manager._tools["run_sql_on_parquet"].fn,
        }
@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    session_path = tmp_path / TEST_WORKSPACE_ID / TEST_AGENT_ID / TEST_SESSION_ID
    session_path.mkdir(parents=True, exist_ok=True)
    return session_path

@pytest.fixture
def sample_parquet_data(session_dir: Path):
    """Fixture to provide sample parquet data."""
    parquet_file = session_dir / "sample.parquet"
    duckdb.sql(
        """
        CREATE OR REPLACE TABLE sample_data AS
        SELECT * FROM (VALUES
            (1, 'Alice', 30),
            (2, 'Bob', 25),
            (3, 'Charlie', 35)
        ) AS v(id, name, age);
        """
    )
    duckdb.sql(f"COPY sample_data TO '{parquet_file}' (FORMAT parquet);")
    return parquet_file

class TestParquetTool:
    """Test cases for Parquet tool."""
    def test_parquet_info(self, parquet_tools, sample_parquet_data):
        """Test the parquet_info function."""
        parquet_info = parquet_tools["parquet_info"]
        result = parquet_info(
            file_path=sample_parquet_data.name,
            workspace_id=TEST_WORKSPACE_ID,
            agent_id=TEST_AGENT_ID,
            session_id=TEST_SESSION_ID,
            columns_limit=10,
        )
        assert "columns" in result
        assert "row_count" in result
        assert result["row_count"] == 3

    def test_parquet_preview(self, parquet_tools, sample_parquet_data):
        """Test the parquet_preview function."""
        parquet_preview = parquet_tools["parquet_preview"]
        result = parquet_preview(
            file_path=sample_parquet_data.name,
            workspace_id=TEST_WORKSPACE_ID,
            agent_id=TEST_AGENT_ID,
            session_id=TEST_SESSION_ID,
            limit=2,
        )
        assert "rows" in result
        assert [row["name"] for row in result["rows"]] == ["Alice", "Bob"]

    def test_run_sql_on_parquet(self, parquet_tools, sample_parquet_data):
        """Test the run_sql_on_parquet function."""
        run_sql_on_parquet = parquet_tools["run_sql_on_parquet"]
        result = run_sql_on_parquet(
            file_path=sample_parquet_data.name,
            query="",
            workspace_id=TEST_WORKSPACE_ID,
            agent_id=TEST_AGENT_ID,
            session_id=TEST_SESSION_ID,
            selected_columns=["name"],
            filters=[("age", ">", 28)]
        )
        assert "rows" in result
        names = [row["name"] for row in result["rows"]]
        assert names == ["Alice", "Charlie"]

    def test_sample_parquet(self, parquet_tools, sample_parquet_data):
        """Test the sample_parquet function."""
        sample_parquet = parquet_tools["sample_parquet"]
        result = sample_parquet(
            file_path=sample_parquet_data.name,
            n=2,
            workspace_id=TEST_WORKSPACE_ID,
            agent_id=TEST_AGENT_ID,
            session_id=TEST_SESSION_ID,
        )
        assert "rows" in result
        assert [row["name"] for row in result["rows"]] == ["Alice", "Bob"]

    def test_parquet_info_invalid_path(self, parquet_tools):
        """Test parquet_info with an invalid file path."""
        parquet_info = parquet_tools["parquet_info"]
        result = parquet_info(
            file_path="invalid/path/to/file.parquet",
            workspace_id=TEST_WORKSPACE_ID,
            agent_id=TEST_AGENT_ID,
            session_id=TEST_SESSION_ID,
            columns_limit=10,
        )
        assert "error" in result

    def test_parquet_preview_invalid_path(self, parquet_tools):
        """Test parquet_preview with an invalid file path."""
        parquet_preview = parquet_tools["parquet_preview"]
        result = parquet_preview(
            file_path="invalid/path/to/file.parquet",
            workspace_id=TEST_WORKSPACE_ID,
            agent_id=TEST_AGENT_ID,
            session_id=TEST_SESSION_ID,
            limit=2,
        )
        assert "error" in result



    def test_run_sql_on_parquet_invalid_query(self, parquet_tools, sample_parquet_data):
        """Test run_sql_on_parquet with an invalid SQL query."""
        run_sql_on_parquet = parquet_tools["run_sql_on_parquet"]
        query = "SELECT non_existing_column FROM sample_data;"
        result = run_sql_on_parquet(
            file_path=str(sample_parquet_data),
            query=query,
            workspace_id=TEST_WORKSPACE_ID,
            agent_id=TEST_AGENT_ID,
            session_id=TEST_SESSION_ID,
        )
        assert "error" in result

    def test_sample_parquet_invalid_path(self, parquet_tools):
        """Test sample_parquet with an invalid file path."""
        sample_parquet = parquet_tools["sample_parquet"]
        result = sample_parquet(
            file_path="invalid/path/to/file.parquet",
            n=2,
            workspace_id=TEST_WORKSPACE_ID,
            agent_id=TEST_AGENT_ID,
            session_id=TEST_SESSION_ID,
        )
        assert "error" in result

    def test_run_sql_on_parquet_no_filters(self, parquet_tools, sample_parquet_data):
        """Test run_sql_on_parquet without filters."""
        run_sql_on_parquet = parquet_tools["run_sql_on_parquet"]
        result = run_sql_on_parquet(
            file_path=sample_parquet_data.name,
            query="",
            workspace_id=TEST_WORKSPACE_ID,
            agent_id=TEST_AGENT_ID,
            session_id=TEST_SESSION_ID,
            selected_columns=["name", "age"],
        )
        assert "rows" in result
        assert len(result["rows"]) == 3
        names = [row["name"] for row in result["rows"]]
        assert names == ["Alice", "Bob", "Charlie"]
    def test_run_sql_on_parquet_with_limit(self, parquet_tools, sample_parquet_data):
        """Test run_sql_on_parquet with limit parameter."""
        run_sql_on_parquet = parquet_tools["run_sql_on_parquet"]
        result = run_sql_on_parquet(
            file_path=sample_parquet_data.name,
            query="",
            workspace_id=TEST_WORKSPACE_ID,
            agent_id=TEST_AGENT_ID,
            session_id=TEST_SESSION_ID,
            selected_columns=["name", "age"],
            limit=2,
        )
        assert "rows" in result
        assert len(result["rows"]) == 2
        names = [row["name"] for row in result["rows"]]
        assert names == ["Alice", "Bob"]

    def test_run_sql_on_parquet_with_order_by(self, parquet_tools, sample_parquet_data):
        """Test run_sql_on_parquet with order_by parameter."""
        run_sql_on_parquet = parquet_tools["run_sql_on_parquet"]
        result = run_sql_on_parquet(
            file_path=sample_parquet_data.name,
            query="",
            workspace_id=TEST_WORKSPACE_ID,
            agent_id=TEST_AGENT_ID,
            session_id=TEST_SESSION_ID,
            selected_columns=["name", "age"],
            order_by=["age DESC"],
        )
        assert "rows" in result
        assert len(result["rows"]) == 3
        names = [row["name"] for row in result["rows"]]
        assert names == ["Charlie", "Alice", "Bob"]

    def test_run_sql_on_parquet_with_group_by(self, parquet_tools, sample_parquet_data):
        """Test run_sql_on_parquet with group_by parameter."""
        run_sql_on_parquet = parquet_tools["run_sql_on_parquet"]
        result = run_sql_on_parquet(
            file_path=sample_parquet_data.name,
            query="",
            workspace_id=TEST_WORKSPACE_ID,
            agent_id=TEST_AGENT_ID,
            session_id=TEST_SESSION_ID,
            selected_columns=["age"],
            group_by=["age"],
        )
        assert "rows" in result
        ages = sorted([row["age"] for row in result["rows"]])
        assert ages == [25, 30, 35]

    def test_parquet_preview_zero_limit(self, parquet_tools, sample_parquet_data):
        """Test parquet_preview with zero limit."""
        parquet_preview = parquet_tools["parquet_preview"]
        result = parquet_preview(
            file_path=sample_parquet_data.name,
            workspace_id=TEST_WORKSPACE_ID,
            agent_id=TEST_AGENT_ID,
            session_id=TEST_SESSION_ID,
            limit=0,
        )
        assert "rows" in result
        assert len(result["rows"]) == 1  # Should return at least 1 row
        #

    def test_parquet_preview_excessive_limit(self, parquet_tools, sample_parquet_data):
        """Test parquet_preview with excessive limit."""
        parquet_preview = parquet_tools["parquet_preview"]
        result = parquet_preview(
            file_path=sample_parquet_data.name,
            workspace_id=TEST_WORKSPACE_ID,
            agent_id=TEST_AGENT_ID,
            session_id=TEST_SESSION_ID,
            limit=1000,
        )
        assert "rows" in result
        assert len(result["rows"]) == 3  # Should cap at available rows
    def test_sample_parquet_excessive_n(self, parquet_tools, sample_parquet_data):
        """Test sample_parquet with excessive n."""
        sample_parquet = parquet_tools["sample_parquet"]
        result = sample_parquet(
            file_path=sample_parquet_data.name,
            n=1000,
            workspace_id=TEST_WORKSPACE_ID,
            agent_id=TEST_AGENT_ID,
            session_id=TEST_SESSION_ID,
        )
        assert "rows" in result
        assert len(result["rows"]) == 3  # Should cap at available rows
    def test_run_sql_on_parquet_no_selected_columns(self, parquet_tools, sample_parquet_data):
        """Test run_sql_on_parquet with no selected_columns parameter."""
        run_sql_on_parquet = parquet_tools["run_sql_on_parquet"]
        result = run_sql_on_parquet(
            file_path=sample_parquet_data.name,
            query="",
            workspace_id=TEST_WORKSPACE_ID,
            agent_id=TEST_AGENT_ID,
            session_id=TEST_SESSION_ID,
        )
        assert "rows" in result
        assert len(result["rows"]) == 3
        names = [row["name"] for row in result["rows"]]
        assert names == ["Alice", "Bob", "Charlie"]

    def test_rejects_path_traversal(self, parquet_tools):
        """Test that path traversal is rejected."""
        parquet_info = parquet_tools["parquet_info"]
        result = parquet_info(
            file_path="../passwd",
            workspace_id=TEST_WORKSPACE_ID,
            agent_id=TEST_AGENT_ID,
            session_id=TEST_SESSION_ID,
            columns_limit=10,
        )
        assert "error" in result
        assert "Access denied" in result["error"]

    def test_reject_non_parquet_extension(tools, tmp_path: Path):
        """Test that non-parquet file extensions are rejected."""
        mcp = FastMCP()
        register_tools(mcp)
        parquet_info = mcp._tool_manager._tools["parquet_info"].fn
        # Create a dummy non-parquet file
        session_dir = tmp_path / TEST_WORKSPACE_ID / TEST_AGENT_ID / TEST_SESSION_ID
        session_dir.mkdir(parents=True, exist_ok=True)
        non_parquet_file = session_dir / "data.txt"
        non_parquet_file.write_text("This is not a parquet file.")

        result = parquet_info(
            file_path=non_parquet_file.name,
            workspace_id=TEST_WORKSPACE_ID,
            agent_id=TEST_AGENT_ID,
            session_id=TEST_SESSION_ID,
            columns_limit=10,
        )
        assert "error" in result
        assert "The file is not a parquet file." in result["error"]
    def test_allow_remote_scheme_passthrough(tools, parquet_tools):
        results = parquet_tools["parquet_info"](
            file_path="s3://my-bucket/data.parquet",
            workspace_id=TEST_WORKSPACE_ID,
            agent_id=TEST_AGENT_ID,
            session_id=TEST_SESSION_ID,
            columns_limit=10,
        )
        assert "error" in results or "columns" in results





