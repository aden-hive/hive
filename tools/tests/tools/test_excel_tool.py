"""Tests for Excel tool functionality."""

import os
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from aden_tools.tools.excel_tool import register_tools
from fastmcp import FastMCP


@pytest.fixture
def mcp_server():
    """Create MCP server with Excel tools registered."""
    mcp = FastMCP("test-excel")
    register_tools(mcp)
    return mcp


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def sample_excel_file(temp_dir):
    """Create a sample Excel file for testing."""
    file_path = os.path.join(temp_dir, "test.xlsx")
    
    # Create sample data
    data = {
        "Name": ["Alice", "Bob", "Charlie"],
        "Age": [25, 30, 35],
        "City": ["New York", "London", "Tokyo"]
    }
    df = pd.DataFrame(data)
    df.to_excel(file_path, sheet_name="Sheet1", index=False)
    
    return file_path


class TestExcelRead:
    """Test excel_read functionality."""

    def test_read_existing_file(self, mcp_server, sample_excel_file, temp_dir):
        """Test reading an existing Excel file."""
        rel_path = "test.xlsx"
        
        # Mock the security path function to return our test file
        import aden_tools.tools.excel_tool.excel_tool as excel_module
        
        def mock_get_secure_path(path, workspace_id, agent_id, session_id):
            return sample_excel_file
        
        original_get_secure_path = excel_module.get_secure_path
        excel_module.get_secure_path = mock_get_secure_path
        
        try:
            # Test the function exists and is callable
            tools = {tool.name: tool for tool in mcp_server.list_tools()}
            assert "excel_read" in tools
            
            # Test reading the file
            result = tools["excel_read"].call(
                path=rel_path,
                workspace_id="test_workspace",
                agent_id="test_agent",
                session_id="test_session"
            )
            
            assert result["success"] is True
            assert result["path"] == rel_path
            assert result["columns"] == ["Name", "Age", "City"]
            assert result["row_count"] == 3
            assert result["total_rows"] == 3
            assert len(result["rows"]) == 3
            
        finally:
            excel_module.get_secure_path = original_get_secure_path

    def test_read_nonexistent_file(self, mcp_server):
        """Test reading a non-existent file returns error."""
        import aden_tools.tools.excel_tool.excel_tool as excel_module
        
        def mock_get_secure_path(path, workspace_id, agent_id, session_id):
            return "/nonexistent/file.xlsx"
        
        original_get_secure_path = excel_module.get_secure_path
        excel_module.get_secure_path = mock_get_secure_path
        
        try:
            tools = {tool.name: tool for tool in mcp_server.list_tools()}
            result = tools["excel_read"].call(
                path="nonexistent.xlsx",
                workspace_id="test_workspace",
                agent_id="test_agent",
                session_id="test_session"
            )
            
            assert "error" in result
            assert "File not found" in result["error"]
            
        finally:
            excel_module.get_secure_path = original_get_secure_path

    def test_read_with_invalid_extension(self, mcp_server):
        """Test reading file with invalid extension returns error."""
        tools = {tool.name: tool for tool in mcp_server.list_tools()}
        result = tools["excel_read"].call(
            path="test.txt",
            workspace_id="test_workspace",
            agent_id="test_agent",
            session_id="test_session"
        )
        
        assert "error" in result
        assert "must have .xlsx or .xls extension" in result["error"]

    def test_read_with_limit_and_offset(self, mcp_server, sample_excel_file):
        """Test reading with limit and offset parameters."""
        import aden_tools.tools.excel_tool.excel_tool as excel_module
        
        def mock_get_secure_path(path, workspace_id, agent_id, session_id):
            return sample_excel_file
        
        original_get_secure_path = excel_module.get_secure_path
        excel_module.get_secure_path = mock_get_secure_path
        
        try:
            tools = {tool.name: tool for tool in mcp_server.list_tools()}
            result = tools["excel_read"].call(
                path="test.xlsx",
                workspace_id="test_workspace",
                agent_id="test_agent",
                session_id="test_session",
                limit=2,
                offset=1
            )
            
            assert result["success"] is True
            assert result["row_count"] == 2
            assert result["total_rows"] == 3
            assert result["offset"] == 1
            assert result["limit"] == 2
            
        finally:
            excel_module.get_secure_path = original_get_secure_path


class TestExcelWrite:
    """Test excel_write functionality."""

    def test_write_new_file(self, mcp_server, temp_dir):
        """Test writing data to a new Excel file."""
        output_path = os.path.join(temp_dir, "output.xlsx")
        
        import aden_tools.tools.excel_tool.excel_tool as excel_module
        
        def mock_get_secure_path(path, workspace_id, agent_id, session_id):
            return output_path
        
        original_get_secure_path = excel_module.get_secure_path
        excel_module.get_secure_path = mock_get_secure_path
        
        try:
            tools = {tool.name: tool for tool in mcp_server.list_tools()}
            
            # Test data
            columns = ["Product", "Price", "Stock"]
            rows = [
                {"Product": "Laptop", "Price": 999.99, "Stock": 10},
                {"Product": "Mouse", "Price": 29.99, "Stock": 50}
            ]
            
            result = tools["excel_write"].call(
                path="output.xlsx",
                workspace_id="test_workspace",
                agent_id="test_agent",
                session_id="test_session",
                columns=columns,
                rows=rows,
                sheet_name="Products"
            )
            
            assert result["success"] is True
            assert result["path"] == "output.xlsx"
            assert result["sheet"] == "Products"
            assert result["rows_written"] == 2
            
            # Verify file was created and contains correct data
            assert os.path.exists(output_path)
            df = pd.read_excel(output_path, sheet_name="Products")
            assert len(df) == 2
            assert list(df.columns) == columns
            
        finally:
            excel_module.get_secure_path = original_get_secure_path

    def test_write_empty_columns_error(self, mcp_server):
        """Test writing with empty columns returns error."""
        tools = {tool.name: tool for tool in mcp_server.list_tools()}
        result = tools["excel_write"].call(
            path="output.xlsx",
            workspace_id="test_workspace",
            agent_id="test_agent",
            session_id="test_session",
            columns=[],
            rows=[]
        )
        
        assert "error" in result
        assert "columns cannot be empty" in result["error"]


class TestExcelInfo:
    """Test excel_info functionality."""

    def test_get_file_info(self, mcp_server, sample_excel_file):
        """Test getting information about an Excel file."""
        import aden_tools.tools.excel_tool.excel_tool as excel_module
        
        def mock_get_secure_path(path, workspace_id, agent_id, session_id):
            return sample_excel_file
        
        original_get_secure_path = excel_module.get_secure_path
        excel_module.get_secure_path = mock_get_secure_path
        
        try:
            tools = {tool.name: tool for tool in mcp_server.list_tools()}
            result = tools["excel_info"].call(
                path="test.xlsx",
                workspace_id="test_workspace",
                agent_id="test_agent",
                session_id="test_session"
            )
            
            assert result["success"] is True
            assert result["path"] == "test.xlsx"
            assert result["sheet_count"] == 1
            assert "file_size" in result
            assert len(result["sheets"]) == 1
            
            sheet_info = result["sheets"][0]
            assert sheet_info["name"] == "Sheet1"
            assert sheet_info["columns"] == ["Name", "Age", "City"]
            assert sheet_info["row_count"] == 3
            
        finally:
            excel_module.get_secure_path = original_get_secure_path


class TestExcelCreateSheet:
    """Test excel_create_sheet functionality."""

    def test_create_sheet_new_file(self, mcp_server, temp_dir):
        """Test creating a sheet in a new file."""
        output_path = os.path.join(temp_dir, "new_file.xlsx")
        
        import aden_tools.tools.excel_tool.excel_tool as excel_module
        
        def mock_get_secure_path(path, workspace_id, agent_id, session_id):
            return output_path
        
        original_get_secure_path = excel_module.get_secure_path
        excel_module.get_secure_path = mock_get_secure_path
        
        try:
            tools = {tool.name: tool for tool in mcp_server.list_tools()}
            
            result = tools["excel_create_sheet"].call(
                path="new_file.xlsx",
                workspace_id="test_workspace",
                agent_id="test_agent",
                session_id="test_session",
                sheet_name="TestSheet",
                columns=["A", "B", "C"],
                rows=[{"A": 1, "B": 2, "C": 3}]
            )
            
            assert result["success"] is True
            assert result["file_created"] is True
            assert result["sheet"] == "TestSheet"
            assert result["rows_written"] == 1
            
            # Verify file exists
            assert os.path.exists(output_path)
            
        finally:
            excel_module.get_secure_path = original_get_secure_path


class TestParameterValidation:
    """Test parameter validation."""

    def test_negative_offset(self, mcp_server):
        """Test that negative offset returns error."""
        tools = {tool.name: tool for tool in mcp_server.list_tools()}
        result = tools["excel_read"].call(
            path="test.xlsx",
            workspace_id="test_workspace",
            agent_id="test_agent",
            session_id="test_session",
            offset=-1
        )
        
        assert "error" in result
        assert "must be non-negative" in result["error"]

    def test_negative_limit(self, mcp_server):
        """Test that negative limit returns error."""
        tools = {tool.name: tool for tool in mcp_server.list_tools()}
        result = tools["excel_read"].call(
            path="test.xlsx",
            workspace_id="test_workspace",
            agent_id="test_agent",
            session_id="test_session",
            limit=-1
        )
        
        assert "error" in result
        assert "must be non-negative" in result["error"]


if __name__ == "__main__":
    pytest.main([__file__])