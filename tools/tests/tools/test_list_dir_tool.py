"""Tests for list_dir tool."""
import os
import sys
import pytest
from pathlib import Path
from fastmcp import FastMCP
from aden_tools.tools.file_system_toolkits.list_dir.list_dir import register_tools
from unittest.mock import patch

@pytest.fixture
def list_dir_fn(mcp: FastMCP):
    """Register and return the list_dir tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["list_dir"].fn

@patch("aden_tools.tools.file_system_toolkits.list_dir.list_dir.get_secure_path")
class TestListDirTool:
    """Tests for list_dir tool."""

    @patch("aden_tools.tools.file_system_toolkits.list_dir.list_dir.os.path.getsize")
    @patch("aden_tools.tools.file_system_toolkits.list_dir.list_dir.os.path.exists")
    @patch("aden_tools.tools.file_system_toolkits.list_dir.list_dir.os.path.islink")
    @patch("aden_tools.tools.file_system_toolkits.list_dir.list_dir.os.path.isdir")
    @patch("aden_tools.tools.file_system_toolkits.list_dir.list_dir.os.listdir")
    def test_list_dir_mocked_symlinks(self, mock_listdir, mock_isdir, mock_islink, mock_exists, mock_getsize, mock_secure, list_dir_fn):
        """Test symlink logic with mocks (works on Windows without admin)."""
        # Setup path mock
        mock_secure.return_value = "/secure/path"
        
        # Setup file system structure
        mock_listdir.return_value = ["broken_link", "valid_link", "regular_file"]
        
        def islink_side_effect(path):
            return "link" in path
            
        def exists_side_effect(path):
            if "broken_link" in path: return False
            return True
            
        def isdir_side_effect(path):
            if "regular_file" in path: return False # file
            if "valid_link" in path: return False # points to file
            return False
            
        mock_islink.side_effect = islink_side_effect
        mock_exists.side_effect = exists_side_effect
        mock_isdir.side_effect = isdir_side_effect
        mock_getsize.return_value = 100
        
        result = list_dir_fn(
            path="/some/path",
            workspace_id="ws1",
            agent_id="ag1",
            session_id="sess1"
        )
        
        assert result["success"] is True
        entries = {e["name"]: e for e in result["entries"]}
        
        # Verify broken link
        assert entries["broken_link"]["type"] == "symlink"
        assert entries["broken_link"]["broken"] is True
        assert entries["broken_link"]["size_bytes"] is None
        
        # Verify valid link
        assert entries["valid_link"]["type"] == "symlink"
        assert entries["valid_link"]["broken"] is False
        assert entries["valid_link"]["size_bytes"] == 100
        
        # Verify regular file
        assert entries["regular_file"]["type"] == "file"
        assert entries["regular_file"]["broken"] is False

    def test_list_dir_basic(self, mock_secure, list_dir_fn, tmp_path: Path):
        """Test listing normal files and directories."""
        mock_secure.side_effect = lambda p, w, a, s: str(Path(p).resolve()) if os.path.isabs(p) else str((tmp_path / p).resolve())
        
        (tmp_path / "file1.txt").write_text("hello")
        (tmp_path / "subdir").mkdir()

        result = list_dir_fn(
            path=str(tmp_path),
            workspace_id="ws1",
            agent_id="ag1",
            session_id="sess1"
        )
        
        assert result["success"] is True
        entries = {e["name"]: e for e in result["entries"]}
        
        assert "file1.txt" in entries
        assert entries["file1.txt"]["type"] == "file"
        assert entries["file1.txt"]["size_bytes"] == 5
        
        assert "subdir" in entries
        assert entries["subdir"]["type"] == "directory"
