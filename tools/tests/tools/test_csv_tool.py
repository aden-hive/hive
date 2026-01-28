"""Tests for csv_tool - Read and manipulate CSV files."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastmcp import FastMCP
from aden_tools.tools.csv_tool.csv_tool import register_tools
import importlib.util

duckdb_available = importlib.util.find_spec("duckdb") is not None

# Test IDs for sandbox
TEST_WORKSPACE_ID = "test-workspace"
TEST_AGENT_ID = "test-agent"
TEST_SESSION_ID = "test-session"


@pytest.fixture
def csv_tools(mcp: FastMCP, tmp_path: Path):
    """Register all CSV tools and return them as a dict."""
    with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
        register_tools(mcp)
        yield {
            "csv_read": mcp._tool_manager._tools["csv_read"].fn,
            "csv_write": mcp._tool_manager._tools["csv_write"].fn,
            "csv_append": mcp._tool_manager._tools["csv_append"].fn,
            "csv_info": mcp._tool_manager._tools["csv_info"].fn,
            "csv_sql": mcp._tool_manager._tools["csv_sql"].fn,
        }


@pytest.fixture
def csv_tool_fn(csv_tools):
    """Return csv_read function for backward compatibility."""
    return csv_tools["csv_read"]


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    """Create and return the session directory within the sandbox."""
    session_path = tmp_path / TEST_WORKSPACE_ID / TEST_AGENT_ID / TEST_SESSION_ID
    session_path.mkdir(parents=True, exist_ok=True)
    return session_path


@pytest.fixture
def basic_csv(session_dir: Path) -> Path:
    """Create a basic CSV file for testing."""
    csv_file = session_dir / "basic.csv"
    csv_file.write_text("name,age,city\nAlice,30,NYC\nBob,25,LA\nCharlie,35,Chicago\n")
    return csv_file


@pytest.fixture
def large_csv(session_dir: Path) -> Path:
    """Create a larger CSV file for pagination testing."""
    csv_file = session_dir / "large.csv"
    lines = ["id,value"]
    for i in range(100):
        lines.append(f"{i},{i * 10}")
    csv_file.write_text("\n".join(lines) + "\n")
    return csv_file


@pytest.fixture
def empty_csv(session_dir: Path) -> Path:
    """Create an empty CSV file (no content)."""
    csv_file = session_dir / "empty.csv"
    csv_file.write_text("")
    return csv_file


@pytest.fixture
def headers_only_csv(session_dir: Path) -> Path:
    """Create a CSV file with only headers."""
    csv_file = session_dir / "headers_only.csv"
    csv_file.write_text("name,age,city\n")
    return csv_file


class TestCsvRead:
    """Tests for csv_read function."""

    def test_read_basic_csv(self, csv_tool_fn, basic_csv, tmp_path):
        """Read a basic CSV file successfully."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tool_fn(
                path="basic.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert result["success"] is True
        assert result["columns"] == ["name", "age", "city"]
        assert result["column_count"] == 3
        assert result["row_count"] == 3
        assert result["total_rows"] == 3
        assert len(result["rows"]) == 3
        assert result["rows"][0] == {"name": "Alice", "age": "30", "city": "NYC"}

    def test_read_with_limit(self, csv_tool_fn, basic_csv, tmp_path):
        """Read CSV with row limit."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tool_fn(
                path="basic.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                limit=2,
            )

        assert result["success"] is True
        assert result["row_count"] == 2
        assert result["total_rows"] == 3
        assert result["limit"] == 2
        assert len(result["rows"]) == 2
        assert result["rows"][0]["name"] == "Alice"
        assert result["rows"][1]["name"] == "Bob"

    def test_read_with_offset(self, csv_tool_fn, basic_csv, tmp_path):
        """Read CSV with row offset."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tool_fn(
                path="basic.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                offset=1,
            )

        assert result["success"] is True
        assert result["row_count"] == 2
        assert result["offset"] == 1
        assert result["rows"][0]["name"] == "Bob"
        assert result["rows"][1]["name"] == "Charlie"

    def test_read_with_limit_and_offset(self, csv_tool_fn, large_csv, tmp_path):
        """Read CSV with both limit and offset (pagination)."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tool_fn(
                path="large.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                limit=10,
                offset=50,
            )

        assert result["success"] is True
        assert result["row_count"] == 10
        assert result["total_rows"] == 100
        assert result["offset"] == 50
        assert result["limit"] == 10
        # First row should be id=50
        assert result["rows"][0] == {"id": "50", "value": "500"}

    def test_file_not_found(self, csv_tool_fn, session_dir, tmp_path):
        """Return error for non-existent file."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tool_fn(
                path="nonexistent.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_non_csv_extension(self, csv_tool_fn, session_dir, tmp_path):
        """Return error for non-CSV file extension."""
        # Create a text file
        txt_file = session_dir / "data.txt"
        txt_file.write_text("name,age\nAlice,30\n")

        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tool_fn(
                path="data.txt",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert "error" in result
        assert ".csv" in result["error"].lower()

    def test_empty_csv_file(self, csv_tool_fn, empty_csv, tmp_path):
        """Return error for empty CSV file."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tool_fn(
                path="empty.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert "error" in result
        assert "empty" in result["error"].lower() or "no headers" in result["error"].lower()

    def test_headers_only_csv(self, csv_tool_fn, headers_only_csv, tmp_path):
        """Read CSV with only headers (no data rows)."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tool_fn(
                path="headers_only.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert result["success"] is True
        assert result["columns"] == ["name", "age", "city"]
        assert result["row_count"] == 0
        assert result["total_rows"] == 0
        assert result["rows"] == []

    def test_missing_workspace_id(self, csv_tool_fn, basic_csv, tmp_path):
        """Return error when workspace_id is missing."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tool_fn(
                path="basic.csv",
                workspace_id="",
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert "error" in result

    def test_missing_agent_id(self, csv_tool_fn, basic_csv, tmp_path):
        """Return error when agent_id is missing."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tool_fn(
                path="basic.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id="",
                session_id=TEST_SESSION_ID,
            )

        assert "error" in result

    def test_missing_session_id(self, csv_tool_fn, basic_csv, tmp_path):
        """Return error when session_id is missing."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tool_fn(
                path="basic.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id="",
            )

        assert "error" in result

    def test_unicode_content(self, csv_tool_fn, session_dir, tmp_path):
        """Read CSV with Unicode content."""
        csv_file = session_dir / "unicode.csv"
        csv_file.write_text("名前,年齢,都市\n太郎,30,東京\nAlice,25,北京\n", encoding="utf-8")

        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tool_fn(
                path="unicode.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert result["success"] is True
        assert result["columns"] == ["名前", "年齢", "都市"]
        assert result["rows"][0]["名前"] == "太郎"
        assert result["rows"][0]["都市"] == "東京"

    def test_quoted_fields(self, csv_tool_fn, session_dir, tmp_path):
        """Read CSV with quoted fields containing commas."""
        csv_file = session_dir / "quoted.csv"
        csv_file.write_text(
            'name,address,note\n"Smith, John","123 Main St, Apt 4","Hello, world"\n'
        )

        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tool_fn(
                path="quoted.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert result["success"] is True
        assert result["rows"][0]["name"] == "Smith, John"
        assert result["rows"][0]["address"] == "123 Main St, Apt 4"

    def test_path_traversal_blocked(self, csv_tool_fn, session_dir, tmp_path):
        """Prevent path traversal attacks."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tool_fn(
                path="../../../etc/passwd",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert "error" in result

    def test_offset_beyond_rows(self, csv_tool_fn, basic_csv, tmp_path):
        """Offset beyond available rows returns empty result."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tool_fn(
                path="basic.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                offset=100,
            )

        assert result["success"] is True
        assert result["row_count"] == 0
        assert result["rows"] == []
        assert result["total_rows"] == 3


class TestCsvWrite:
    """Tests for csv_write function."""

    def test_write_new_csv(self, csv_tools, session_dir, tmp_path):
        """Write a new CSV file successfully."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_write"](
                path="output.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                columns=["name", "age", "city"],
                rows=[
                    {"name": "Alice", "age": "30", "city": "NYC"},
                    {"name": "Bob", "age": "25", "city": "LA"},
                ],
            )

        assert result["success"] is True
        assert result["columns"] == ["name", "age", "city"]
        assert result["column_count"] == 3
        assert result["rows_written"] == 2

        # Verify file content
        content = (session_dir / "output.csv").read_text()
        assert "name,age,city" in content
        assert "Alice,30,NYC" in content
        assert "Bob,25,LA" in content

    def test_write_creates_parent_directories(self, csv_tools, session_dir, tmp_path):
        """Write creates parent directories if needed."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_write"](
                path="subdir/nested/output.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                columns=["id"],
                rows=[{"id": "1"}],
            )

        assert result["success"] is True
        assert (session_dir / "subdir" / "nested" / "output.csv").exists()

    def test_write_empty_columns_error(self, csv_tools, session_dir, tmp_path):
        """Return error when columns is empty."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_write"](
                path="output.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                columns=[],
                rows=[],
            )

        assert "error" in result
        assert "empty" in result["error"].lower()

    def test_write_non_csv_extension_error(self, csv_tools, session_dir, tmp_path):
        """Return error for non-CSV file extension."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_write"](
                path="output.txt",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                columns=["id"],
                rows=[],
            )

        assert "error" in result
        assert ".csv" in result["error"].lower()

    def test_write_filters_extra_columns(self, csv_tools, session_dir, tmp_path):
        """Extra columns in rows are filtered out."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_write"](
                path="output.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                columns=["name"],
                rows=[{"name": "Alice", "extra": "ignored"}],
            )

        assert result["success"] is True

        content = (session_dir / "output.csv").read_text()
        assert "extra" not in content
        assert "ignored" not in content

    def test_write_empty_rows(self, csv_tools, session_dir, tmp_path):
        """Write CSV with headers but no rows."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_write"](
                path="output.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                columns=["name", "age"],
                rows=[],
            )

        assert result["success"] is True
        assert result["rows_written"] == 0

        content = (session_dir / "output.csv").read_text()
        assert "name,age" in content

    def test_write_unicode_content(self, csv_tools, session_dir, tmp_path):
        """Write CSV with Unicode content."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_write"](
                path="unicode.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                columns=["名前", "都市"],
                rows=[{"名前": "太郎", "都市": "東京"}],
            )

        assert result["success"] is True

        content = (session_dir / "unicode.csv").read_text(encoding="utf-8")
        assert "太郎" in content
        assert "東京" in content


class TestCsvAppend:
    """Tests for csv_append function."""

    def test_append_to_existing_csv(self, csv_tools, basic_csv, tmp_path):
        """Append rows to an existing CSV file."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_append"](
                path="basic.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                rows=[
                    {"name": "David", "age": "28", "city": "Seattle"},
                    {"name": "Eve", "age": "32", "city": "Boston"},
                ],
            )

        assert result["success"] is True
        assert result["rows_appended"] == 2
        assert result["total_rows"] == 5

    def test_append_file_not_found(self, csv_tools, session_dir, tmp_path):
        """Return error when file doesn't exist."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_append"](
                path="nonexistent.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                rows=[{"name": "Alice"}],
            )

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_append_empty_rows_error(self, csv_tools, basic_csv, tmp_path):
        """Return error when rows is empty."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_append"](
                path="basic.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                rows=[],
            )

        assert "error" in result
        assert "empty" in result["error"].lower()

    def test_append_filters_extra_columns(self, csv_tools, basic_csv, session_dir, tmp_path):
        """Extra columns in rows are filtered out based on existing headers."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_append"](
                path="basic.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                rows=[{"name": "David", "age": "28", "city": "Seattle", "extra": "ignored"}],
            )

        assert result["success"] is True

        content = (session_dir / "basic.csv").read_text()
        assert "extra" not in content
        assert "ignored" not in content
        assert "David" in content

    def test_append_non_csv_extension_error(self, csv_tools, session_dir, tmp_path):
        """Return error for non-CSV file extension."""
        txt_file = session_dir / "data.txt"
        txt_file.write_text("name\nAlice\n")

        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_append"](
                path="data.txt",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                rows=[{"name": "Bob"}],
            )

        assert "error" in result
        assert ".csv" in result["error"].lower()


class TestCsvInfo:
    """Tests for csv_info function."""

    def test_get_info_basic_csv(self, csv_tools, basic_csv, tmp_path):
        """Get info about a basic CSV file."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_info"](
                path="basic.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert result["success"] is True
        assert result["columns"] == ["name", "age", "city"]
        assert result["column_count"] == 3
        assert result["total_rows"] == 3
        assert "file_size_bytes" in result
        assert result["file_size_bytes"] > 0

    def test_get_info_large_csv(self, csv_tools, large_csv, tmp_path):
        """Get info about a large CSV file."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_info"](
                path="large.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert result["success"] is True
        assert result["total_rows"] == 100
        assert result["columns"] == ["id", "value"]

    def test_get_info_file_not_found(self, csv_tools, session_dir, tmp_path):
        """Return error when file doesn't exist."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_info"](
                path="nonexistent.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_get_info_empty_csv(self, csv_tools, empty_csv, tmp_path):
        """Return error for empty CSV file."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_info"](
                path="empty.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert "error" in result
        assert "empty" in result["error"].lower() or "no headers" in result["error"].lower()

    def test_get_info_headers_only(self, csv_tools, headers_only_csv, tmp_path):
        """Get info about CSV with only headers."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_info"](
                path="headers_only.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert result["success"] is True
        assert result["columns"] == ["name", "age", "city"]
        assert result["total_rows"] == 0

    def test_get_info_non_csv_extension_error(self, csv_tools, session_dir, tmp_path):
        """Return error for non-CSV file extension."""
        txt_file = session_dir / "data.txt"
        txt_file.write_text("name\nAlice\n")

        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_info"](
                path="data.txt",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert "error" in result
        assert ".csv" in result["error"].lower()


@pytest.mark.skipif(not duckdb_available, reason="duckdb not installed")
class TestCsvSql:
    """Tests for csv_sql function (requires duckdb)."""

    @pytest.fixture
    def products_csv(self, session_dir: Path) -> Path:
        """Create a products CSV for SQL testing."""
        csv_file = session_dir / "products.csv"
        csv_file.write_text(
            "id,name,category,price,stock\n"
            "1,iPhone,Electronics,999,50\n"
            "2,MacBook,Electronics,1999,30\n"
            "3,Coffee Mug,Kitchen,15,200\n"
            "4,Headphones,Electronics,299,75\n"
            "5,Water Bottle,Kitchen,25,150\n"
        )
        return csv_file

    def test_basic_select(self, csv_tools, products_csv, tmp_path):
        """Execute basic SELECT query."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_sql"](
                path="products.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                query="SELECT * FROM data",
            )

        assert result["success"] is True
        assert result["row_count"] == 5
        assert "id" in result["columns"]
        assert "name" in result["columns"]

    def test_where_clause(self, csv_tools, products_csv, tmp_path):
        """Filter with WHERE clause."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_sql"](
                path="products.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                query="SELECT name, price FROM data WHERE price > 500",
            )

        assert result["success"] is True
        assert result["row_count"] == 2
        names = [row["name"] for row in result["rows"]]
        assert "iPhone" in names
        assert "MacBook" in names

    def test_aggregate_functions(self, csv_tools, products_csv, tmp_path):
        """Use aggregate functions."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_sql"](
                path="products.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                query=(
                    "SELECT category, COUNT(*) as count, "
                    "AVG(price) as avg_price FROM data GROUP BY category"
                ),
            )

        assert result["success"] is True
        assert result["row_count"] == 2  # Electronics and Kitchen

    def test_order_by_and_limit(self, csv_tools, products_csv, tmp_path):
        """Sort and limit results."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_sql"](
                path="products.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                query="SELECT name, price FROM data ORDER BY price DESC LIMIT 2",
            )

        assert result["success"] is True
        assert result["row_count"] == 2
        assert result["rows"][0]["name"] == "MacBook"
        assert result["rows"][1]["name"] == "iPhone"

    def test_like_search(self, csv_tools, products_csv, tmp_path):
        """Search with LIKE operator."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_sql"](
                path="products.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                query="SELECT * FROM data WHERE LOWER(name) LIKE '%book%'",
            )

        assert result["success"] is True
        assert result["row_count"] == 1
        assert result["rows"][0]["name"] == "MacBook"

    def test_file_not_found(self, csv_tools, session_dir, tmp_path):
        """Return error for non-existent file."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_sql"](
                path="nonexistent.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                query="SELECT * FROM data",
            )

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_empty_query_error(self, csv_tools, products_csv, tmp_path):
        """Return error for empty query."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_sql"](
                path="products.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                query="",
            )

        assert "error" in result
        assert "empty" in result["error"].lower()

    def test_non_select_blocked(self, csv_tools, products_csv, tmp_path):
        """Block non-SELECT queries for security."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_sql"](
                path="products.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                query="DELETE FROM data WHERE id = 1",
            )

        assert "error" in result
        assert "select" in result["error"].lower()

    def test_drop_blocked(self, csv_tools, products_csv, tmp_path):
        """Block DROP statements."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_sql"](
                path="products.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                query="DROP TABLE data",
            )

        assert "error" in result

    def test_insert_blocked(self, csv_tools, products_csv, tmp_path):
        """Block INSERT statements."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_sql"](
                path="products.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                query="INSERT INTO data VALUES (6, 'Test', 'Test', 10, 10)",
            )

        assert "error" in result

    def test_invalid_sql_syntax(self, csv_tools, products_csv, tmp_path):
        """Return error for invalid SQL syntax."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_sql"](
                path="products.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                query="SELEKT * FORM data",
            )

        assert "error" in result

    def test_unicode_data(self, csv_tools, session_dir, tmp_path):
        """Query CSV with Unicode content."""
        csv_file = session_dir / "unicode.csv"
        csv_file.write_text("名前,価格\n商品A,100\n商品B,200\n", encoding="utf-8")

        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = csv_tools["csv_sql"](
                path="unicode.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                query="SELECT * FROM data WHERE 価格 > 150",
            )

        assert result["success"] is True
        assert result["row_count"] == 1
        assert result["rows"][0]["名前"] == "商品B"
