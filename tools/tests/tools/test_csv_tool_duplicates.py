from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.csv_tool.csv_tool import register_tools


class TestCsvDuplicates:
    @pytest.fixture
    def csv_read(self):
        mcp = FastMCP("test")
        register_tools(mcp)
        return mcp._tool_manager._tools["csv_read"].fn

    @pytest.fixture
    def csv_write(self):
        mcp = FastMCP("test")
        register_tools(mcp)
        return mcp._tool_manager._tools["csv_write"].fn

    def test_csv_read_detects_duplicates(self, csv_read, tmp_path):
        csv_file = tmp_path / "dupes.csv"
        csv_file.write_text("name,age,name\nAlice,30,Alice2")

        with patch(
            "aden_tools.tools.csv_tool.csv_tool.get_secure_path",
            return_value=str(csv_file),
        ):
            result = csv_read(path="dupes.csv", workspace_id="w", agent_id="a", session_id="s")

        assert "error" in result
        assert "duplicate column names" in result["error"]
        assert "name" in result["duplicate_columns"]

    def test_csv_write_detects_duplicates(self, csv_write, tmp_path):
        csv_file = tmp_path / "out.csv"

        with patch(
            "aden_tools.tools.csv_tool.csv_tool.get_secure_path",
            return_value=str(csv_file),
        ):
            result = csv_write(
                path="out.csv",
                workspace_id="w",
                agent_id="a",
                session_id="s",
                columns=["id", "name", "id"],
                rows=[{"id": "1", "name": "test"}],
            )

        assert "error" in result
        assert "duplicate column names" in result["error"]
