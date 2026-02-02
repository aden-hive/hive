"""Tests for excel_tool - Read and manipulate Excel files using pandas."""

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from fastmcp import FastMCP

from aden_tools.tools.excel_tool.excel_tool import register_tools

# Skip all tests if openpyxl is not installed
pytest.importorskip("openpyxl", reason="openpyxl required for Excel tests")

# Test IDs for sandbox
TEST_WORKSPACE_ID = "test-workspace"
TEST_AGENT_ID = "test-agent"
TEST_SESSION_ID = "test-session"


@pytest.fixture
def mcp() -> FastMCP:
    """Create a fresh FastMCP instance for testing."""
    return FastMCP("test-server")


@pytest.fixture
def excel_tools(mcp: FastMCP, tmp_path: Path):
    """Register all Excel tools and return them as a dict."""
    with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
        register_tools(mcp)
        yield {
            "excel_read": mcp._tool_manager._tools["excel_read"].fn,
            "excel_write": mcp._tool_manager._tools["excel_write"].fn,
            "excel_append": mcp._tool_manager._tools["excel_append"].fn,
            "excel_info": mcp._tool_manager._tools["excel_info"].fn,
            "excel_list_sheets": mcp._tool_manager._tools["excel_list_sheets"].fn,
        }


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    """Create and return the session directory within the sandbox."""
    session_path = tmp_path / TEST_WORKSPACE_ID / TEST_AGENT_ID / TEST_SESSION_ID
    session_path.mkdir(parents=True, exist_ok=True)
    return session_path


@pytest.fixture
def basic_excel(session_dir: Path) -> Path:
    """Create a basic Excel file for testing using pandas."""
    excel_file = session_dir / "basic.xlsx"
    df = pd.DataFrame({
        "Name": ["Alice", "Bob", "Charlie"],
        "Age": [30, 25, 35],
        "City": ["NYC", "LA", "Chicago"],
    })
    df.to_excel(excel_file, index=False, engine="openpyxl")
    return excel_file


@pytest.fixture
def multi_sheet_excel(session_dir: Path) -> Path:
    """Create an Excel file with multiple sheets using pandas."""
    excel_file = session_dir / "multi_sheet.xlsx"
    
    # Create two DataFrames
    df_sales = pd.DataFrame({
        "Product": ["Widget", "Gadget"],
        "Quantity": [100, 50],
        "Price": [9.99, 19.99],
    })
    df_inventory = pd.DataFrame({
        "Item": ["Widget", "Gadget"],
        "Stock": [500, 200],
    })
    
    # Write to Excel with multiple sheets
    with pd.ExcelWriter(excel_file, engine="openpyxl") as writer:
        df_sales.to_excel(writer, sheet_name="Sales", index=False)
        df_inventory.to_excel(writer, sheet_name="Inventory", index=False)
    
    return excel_file


@pytest.fixture
def large_excel(session_dir: Path) -> Path:
    """Create a larger Excel file for pagination testing."""
    excel_file = session_dir / "large.xlsx"
    df = pd.DataFrame({
        "id": list(range(100)),
        "value": [i * 10 for i in range(100)],
    })
    df.to_excel(excel_file, index=False, engine="openpyxl")
    return excel_file


class TestExcelRead:
    """Tests for excel_read function."""

    def test_read_basic_excel(self, excel_tools, basic_excel, tmp_path):
        """Read a basic Excel file successfully."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_read"](
                path="basic.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert result["success"] is True
        assert result["columns"] == ["Name", "Age", "City"]
        assert result["column_count"] == 3
        assert result["row_count"] == 3
        assert result["total_rows"] == 3
        assert len(result["rows"]) == 3
        assert result["rows"][0]["Name"] == "Alice"
        assert result["rows"][0]["Age"] == 30

    def test_read_with_limit(self, excel_tools, basic_excel, tmp_path):
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
        assert result["limit"] == 2
        assert len(result["rows"]) == 2
        assert result["rows"][0]["Name"] == "Alice"
        assert result["rows"][1]["Name"] == "Bob"

    def test_read_with_offset(self, excel_tools, basic_excel, tmp_path):
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
        assert result["rows"][0]["Name"] == "Bob"
        assert result["rows"][1]["Name"] == "Charlie"

    def test_read_with_limit_and_offset(self, excel_tools, large_excel, tmp_path):
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
        # First row should be id=50
        assert result["rows"][0]["id"] == 50
        assert result["rows"][0]["value"] == 500

    def test_negative_limit(self, excel_tools, basic_excel, tmp_path):
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

    def test_negative_offset(self, excel_tools, basic_excel, tmp_path):
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
        # Create a text file
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
        assert "extension" in result["error"].lower()

    def test_read_specific_sheet(self, excel_tools, multi_sheet_excel, tmp_path):
        """Read specific sheet by name."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_read"](
                path="multi_sheet.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                sheet_name="Inventory",
            )

        assert result["success"] is True
        assert result["active_sheet"] == "Inventory"
        assert result["columns"] == ["Item", "Stock"]
        assert result["row_count"] == 2

    def test_read_invalid_sheet_name(self, excel_tools, basic_excel, tmp_path):
        """Return error for non-existent sheet."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_read"](
                path="basic.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                sheet_name="NonExistent",
            )

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_offset_beyond_rows(self, excel_tools, basic_excel, tmp_path):
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


class TestExcelWrite:
    """Tests for excel_write function."""

    def test_write_new_excel(self, excel_tools, session_dir, tmp_path):
        """Write a new Excel file successfully."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_write"](
                path="output.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                columns=["name", "age", "city"],
                rows=[
                    {"name": "Alice", "age": 30, "city": "NYC"},
                    {"name": "Bob", "age": 25, "city": "LA"},
                ],
            )

        assert result["success"] is True
        assert result["columns"] == ["name", "age", "city"]
        assert result["column_count"] == 3
        assert result["rows_written"] == 2
        assert result["sheet_name"] == "Sheet1"

        # Verify file content
        df = pd.read_excel(session_dir / "output.xlsx", engine="openpyxl")
        assert list(df.columns) == ["name", "age", "city"]
        assert len(df) == 2
        assert df.iloc[0]["name"] == "Alice"

    def test_write_custom_sheet_name(self, excel_tools, session_dir, tmp_path):
        """Write with custom sheet name."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_write"](
                path="output.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                columns=["Product"],
                rows=[{"Product": "Widget"}],
                sheet_name="Products",
            )

        assert result["success"] is True
        assert result["sheet_name"] == "Products"

        # Verify sheet name
        excel_file = pd.ExcelFile(session_dir / "output.xlsx", engine="openpyxl")
        assert "Products" in excel_file.sheet_names
        excel_file.close()

    def test_write_creates_parent_directories(self, excel_tools, session_dir, tmp_path):
        """Write creates parent directories if needed."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_write"](
                path="subdir/nested/output.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                columns=["id"],
                rows=[{"id": 1}],
            )

        assert result["success"] is True
        assert (session_dir / "subdir" / "nested" / "output.xlsx").exists()

    def test_write_empty_columns_error(self, excel_tools, session_dir, tmp_path):
        """Return error when columns is empty."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_write"](
                path="output.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                columns=[],
                rows=[],
            )

        assert "error" in result
        assert "empty" in result["error"].lower()

    def test_write_non_excel_extension_error(self, excel_tools, session_dir, tmp_path):
        """Return error for non-Excel file extension."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_write"](
                path="output.csv",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                columns=["id"],
                rows=[],
            )

        assert "error" in result
        assert "extension" in result["error"].lower()

    def test_write_filters_extra_columns(self, excel_tools, session_dir, tmp_path):
        """Extra columns in rows are filtered out."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_write"](
                path="output.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                columns=["name"],
                rows=[{"name": "Alice", "extra": "ignored"}],
            )

        assert result["success"] is True

        df = pd.read_excel(session_dir / "output.xlsx", engine="openpyxl")
        assert "extra" not in df.columns

    def test_write_empty_rows(self, excel_tools, session_dir, tmp_path):
        """Write Excel with headers but no rows."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_write"](
                path="output.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                columns=["name", "age"],
                rows=[],
            )

        assert result["success"] is True
        assert result["rows_written"] == 0

        df = pd.read_excel(session_dir / "output.xlsx", engine="openpyxl")
        assert list(df.columns) == ["name", "age"]
        assert len(df) == 0


class TestExcelAppend:
    """Tests for excel_append function."""

    def test_append_to_existing_excel(self, excel_tools, basic_excel, tmp_path):
        """Append rows to an existing Excel file."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_append"](
                path="basic.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                rows=[
                    {"Name": "David", "Age": 28, "City": "Seattle"},
                    {"Name": "Eve", "Age": 32, "City": "Boston"},
                ],
            )

        assert result["success"] is True
        assert result["rows_appended"] == 2
        assert result["total_rows"] == 5

    def test_append_file_not_found(self, excel_tools, session_dir, tmp_path):
        """Return error when file doesn't exist."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_append"](
                path="nonexistent.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                rows=[{"Name": "Alice"}],
            )

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_append_empty_rows_error(self, excel_tools, basic_excel, tmp_path):
        """Return error when rows is empty."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_append"](
                path="basic.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                rows=[],
            )

        assert "error" in result
        assert "empty" in result["error"].lower()

    def test_append_filters_extra_columns(self, excel_tools, basic_excel, session_dir, tmp_path):
        """Extra columns in rows are filtered out based on existing headers."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_append"](
                path="basic.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                rows=[{"Name": "David", "Age": 28, "City": "Seattle", "extra": "ignored"}],
            )

        assert result["success"] is True

        df = pd.read_excel(session_dir / "basic.xlsx", engine="openpyxl")
        assert "extra" not in df.columns
        assert "David" in df["Name"].values


class TestExcelInfo:
    """Tests for excel_info function."""

    def test_get_info_basic_excel(self, excel_tools, basic_excel, tmp_path):
        """Get info about a basic Excel file."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_info"](
                path="basic.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert result["success"] is True
        assert result["sheet_count"] == 1
        assert "file_size_bytes" in result
        assert result["file_size_bytes"] > 0
        assert len(result["sheets"]) == 1
        assert result["sheets"][0]["columns"] == ["Name", "Age", "City"]
        assert result["sheets"][0]["row_count"] == 3

    def test_get_info_multi_sheet(self, excel_tools, multi_sheet_excel, tmp_path):
        """Get info about multi-sheet Excel file."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_info"](
                path="multi_sheet.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert result["success"] is True
        assert result["sheet_count"] == 2
        assert "Sales" in result["sheet_names"]
        assert "Inventory" in result["sheet_names"]

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


class TestExcelListSheets:
    """Tests for excel_list_sheets function."""

    def test_list_sheets_basic(self, excel_tools, multi_sheet_excel, tmp_path):
        """List sheets in an Excel file."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_list_sheets"](
                path="multi_sheet.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert result["success"] is True
        assert result["sheet_count"] == 2
        assert "Sales" in result["sheet_names"]
        assert "Inventory" in result["sheet_names"]

    def test_list_sheets_file_not_found(self, excel_tools, session_dir, tmp_path):
        """Return error when file doesn't exist."""
        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_list_sheets"](
                path="nonexistent.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert "error" in result
        assert "not found" in result["error"].lower()


class TestExcelDatetimeSerialization:
    """Tests for datetime and special value serialization."""

    def test_datetime_values_serialized(self, excel_tools, session_dir, tmp_path):
        """Datetime values are serialized to ISO format."""
        from datetime import datetime

        # Create Excel file with datetime values
        excel_file = session_dir / "dates.xlsx"
        df = pd.DataFrame({
            "Date": [datetime(2024, 1, 15, 10, 30, 0)],
            "Value": [100],
        })
        df.to_excel(excel_file, index=False, engine="openpyxl")

        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_read"](
                path="dates.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
            )

        assert result["success"] is True
        # Datetime should be converted to ISO string
        assert "2024-01-15" in result["rows"][0]["Date"]

    def test_nan_values_serialized_as_none(self, excel_tools, session_dir, tmp_path):
        """NaN values are serialized as None."""
        import numpy as np

        # Create Excel file with NaN values
        excel_file = session_dir / "with_nan.xlsx"
        df = pd.DataFrame({
            "Name": ["Alice", None, "Charlie"],
            "Age": [30, np.nan, 35],
        })
        df.to_excel(excel_file, index=False, engine="openpyxl")

        with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
            result = excel_tools["excel_read"](
                path="with_nan.xlsx",
                workspace_id=TEST_WORKSPACE_ID,
                agent_id=TEST_AGENT_ID,
                session_id=TEST_SESSION_ID,
                include_empty_rows=True,
            )

        assert result["success"] is True
        # NaN values should be None
        assert result["rows"][1]["Name"] is None
        assert result["rows"][1]["Age"] is None
