"""Tests for excel_tool - Read and query Excel (.xlsx/.xls) files."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.excel_tool.excel_tool import register_tools

duckdb_available = importlib.util.find_spec("duckdb") is not None
openpyxl_available = importlib.util.find_spec("openpyxl") is not None

# Test IDs for sandbox
TEST_WORKSPACE_ID = "test-workspace"
TEST_AGENT_ID = "test-agent"
TEST_SESSION_ID = "test-session"


def _create_xlsx_with_openpyxl(filepath: Path, headers: list[str], rows: list[list]) -> Path:
    """Create an xlsx file using openpyxl."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    wb.save(str(filepath))
    return filepath


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    """Create and return the session directory within the sandbox."""
    session_path = tmp_path / TEST_WORKSPACE_ID / TEST_AGENT_ID / TEST_SESSION_ID
    session_path.mkdir(parents=True, exist_ok=True)
    return session_path


@pytest.fixture
def excel_tools(mcp: FastMCP, tmp_path: Path):
    """Register all Excel tools and return them as a dict."""
    with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
        register_tools(mcp)
        yield {
            "excel_read": mcp._tool_manager._tools["excel_read"].fn,
            "excel_info": mcp._tool_manager._tools["excel_info"].fn,
            "excel_sql": mcp._tool_manager._tools["excel_sql"].fn,
        }


@pytest.fixture
def basic_xlsx(session_dir: Path) -> Path:
    """Create a basic Excel file for testing."""
    return _create_xlsx_with_openpyxl(
        session_dir / "basic.xlsx",
        ["name", "age", "city"],
        [
            ["Alice", 30, "NYC"],
            ["Bob", 25, "LA"],
            ["Charlie", 35, "Chicago"],
        ],
    )


@pytest.fixture
def large_xlsx(session_dir: Path) -> Path:
    """Create a larger Excel file for pagination testing."""
    return _create_xlsx_with_openpyxl(
        session_dir / "large.xlsx",
        ["id", "value"],
        [[i, i * 10] for i in range(100)],
    )


@pytest.fixture
def products_xlsx(session_dir: Path) -> Path:
    """Create a products Excel file for SQL testing."""
    return _create_xlsx_with_openpyxl(
        session_dir / "products.xlsx",
        ["id", "name", "category", "price", "stock"],
        [
            [1, "iPhone", "Electronics", 999, 50],
            [2, "MacBook", "Electronics", 1999, 30],
            [3, "Coffee Mug", "Kitchen", 15, 200],
            [4, "Headphones", "Electronics", 299, 75],
            [5, "Water Bottle", "Kitchen", 25, 150],
        ],
    )


@pytest.mark.skipif(not duckdb_available, reason="duckdb not installed")
@pytest.mark.skipif(not openpyxl_available, reason="openpyxl not installed (test fixture dependency)")
class TestExcelRead:
    """Tests for excel_read function."""

    def test_read_basic_xlsx(self, excel_tools, basic_xlsx, tmp_path):
        """Read a basic Excel file successfully."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_read"](
                path="basic.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert result["success"] is True
        assert "name" in result["columns"]
        assert "age" in result["columns"]
        assert "city" in result["columns"]
        assert result["column_count"] == 3
        assert result["row_count"] == 3
        assert result["total_rows"] == 3

    def test_read_with_limit(self, excel_tools, basic_xlsx, tmp_path):
        """Read Excel with row limit."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_read"](
                path="basic.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                limit=2,
            )

        assert result["success"] is True
        assert result["row_count"] == 2
        assert result["total_rows"] == 3
        assert result["limit"] == 2

    def test_read_with_offset(self, excel_tools, basic_xlsx, tmp_path):
        """Read Excel with row offset."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_read"](
                path="basic.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                offset=1,
            )

        assert result["success"] is True
        assert result["row_count"] == 2
        assert result["offset"] == 1

    def test_read_with_limit_and_offset(self, excel_tools, large_xlsx, tmp_path):
        """Read Excel with both limit and offset (pagination)."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_read"](
                path="large.xlsx",
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

    def test_negative_limit(self, excel_tools, basic_xlsx, tmp_path):
        """Return error for negative limit."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_read"](
                path="basic.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                limit=-1,
            )

        assert "error" in result
        assert "non-negative" in result["error"].lower()

    def test_negative_offset(self, excel_tools, basic_xlsx, tmp_path):
        """Return error for negative offset."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_read"](
                path="basic.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                offset=-1,
            )

        assert "error" in result
        assert "non-negative" in result["error"].lower()

    def test_file_not_found(self, excel_tools, session_dir, tmp_path):
        """Return error for non-existent file."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_read"](
                path="nonexistent.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_non_excel_extension(self, excel_tools, session_dir, tmp_path):
        """Return error for non-Excel file extension."""
        txt_file = session_dir / "data.txt"
        txt_file.write_text("name,age\nAlice,30\n")

        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_read"](
                path="data.txt",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert "error" in result
        assert ".xlsx" in result["error"].lower() or ".xls" in result["error"].lower()

    def test_missing_workspace_id(self, excel_tools, basic_xlsx, tmp_path):
        """Return error when workspace_id is missing."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_read"](
                path="basic.xlsx",
                workspace_id="",
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert "error" in result

    def test_path_traversal_blocked(self, excel_tools, session_dir, tmp_path):
        """Prevent path traversal attacks."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_read"](
                path="../../../etc/passwd.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert "error" in result

    def test_offset_beyond_rows(self, excel_tools, basic_xlsx, tmp_path):
        """Offset beyond available rows returns empty result."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_read"](
                path="basic.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                offset=100,
            )

        assert result["success"] is True
        assert result["row_count"] == 0
        assert result["rows"] == []
        assert result["total_rows"] == 3


@pytest.mark.skipif(not duckdb_available, reason="duckdb not installed")
@pytest.mark.skipif(not openpyxl_available, reason="openpyxl not installed (test fixture dependency)")
class TestExcelInfo:
    """Tests for excel_info function."""

    def test_get_info_basic_xlsx(self, excel_tools, basic_xlsx, tmp_path):
        """Get info about a basic Excel file."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_info"](
                path="basic.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert result["success"] is True
        assert result["sheet_count"] >= 1
        assert len(result["sheets"]) >= 1
        assert "file_size_bytes" in result
        assert result["file_size_bytes"] > 0

        # Check first sheet details
        first_sheet = result["sheets"][0]
        assert "name" in first_sheet
        assert "columns" in first_sheet
        assert "column_count" in first_sheet
        assert "row_count" in first_sheet
        assert first_sheet["row_count"] == 3
        assert first_sheet["column_count"] == 3

    def test_get_info_file_not_found(self, excel_tools, session_dir, tmp_path):
        """Return error when file doesn't exist."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_info"](
                path="nonexistent.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_get_info_non_excel_extension(self, excel_tools, session_dir, tmp_path):
        """Return error for non-Excel file extension."""
        txt_file = session_dir / "data.csv"
        txt_file.write_text("name\nAlice\n")

        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_info"](
                path="data.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert "error" in result
        assert ".xlsx" in result["error"].lower() or ".xls" in result["error"].lower()


@pytest.mark.skipif(not duckdb_available, reason="duckdb not installed")
@pytest.mark.skipif(not openpyxl_available, reason="openpyxl not installed (test fixture dependency)")
class TestExcelSql:
    """Tests for excel_sql function (requires duckdb)."""

    def test_basic_select(self, excel_tools, products_xlsx, tmp_path):
        """Execute basic SELECT query."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_sql"](
                path="products.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                query="SELECT * FROM data",
            )

        assert result["success"] is True
        assert result["row_count"] == 5
        assert "id" in result["columns"]
        assert "name" in result["columns"]

    def test_where_clause(self, excel_tools, products_xlsx, tmp_path):
        """Filter with WHERE clause."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_sql"](
                path="products.xlsx",
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

    def test_aggregate_functions(self, excel_tools, products_xlsx, tmp_path):
        """Use aggregate functions."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_sql"](
                path="products.xlsx",
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

    def test_order_by_and_limit(self, excel_tools, products_xlsx, tmp_path):
        """Sort and limit results."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_sql"](
                path="products.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                query="SELECT name, price FROM data ORDER BY price DESC LIMIT 2",
            )

        assert result["success"] is True
        assert result["row_count"] == 2
        assert result["rows"][0]["name"] == "MacBook"
        assert result["rows"][1]["name"] == "iPhone"

    def test_file_not_found(self, excel_tools, session_dir, tmp_path):
        """Return error for non-existent file."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_sql"](
                path="nonexistent.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                query="SELECT * FROM data",
            )

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_empty_query_error(self, excel_tools, products_xlsx, tmp_path):
        """Return error for empty query."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_sql"](
                path="products.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                query="",
            )

        assert "error" in result
        assert "empty" in result["error"].lower()

    def test_non_select_blocked(self, excel_tools, products_xlsx, tmp_path):
        """Block non-SELECT queries for security."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_sql"](
                path="products.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                query="DELETE FROM data WHERE id = 1",
            )

        assert "error" in result
        assert "select" in result["error"].lower()

    def test_drop_blocked(self, excel_tools, products_xlsx, tmp_path):
        """Block DROP statements."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_sql"](
                path="products.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                query="DROP TABLE data",
            )

        assert "error" in result

    def test_insert_blocked(self, excel_tools, products_xlsx, tmp_path):
        """Block INSERT statements."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_sql"](
                path="products.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                query="INSERT INTO data VALUES (6, 'Test', 'Test', 10, 10)",
            )

        assert "error" in result

    def test_invalid_sql_syntax(self, excel_tools, products_xlsx, tmp_path):
        """Return error for invalid SQL syntax."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_sql"](
                path="products.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                query="SELEKT * FORM data",
            )

        assert "error" in result
