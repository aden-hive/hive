import os
from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.csv_tool.csv_tool import register_tools


class TestCsvDuplicates:
    @pytest.fixture
    def mcp(self):
        mcp = FastMCP("test")
        register_tools(mcp)
        return mcp

    @pytest.fixture
    def csv_read(self, mcp):
        return mcp._tool_manager._tools["csv_read"].fn

    @pytest.fixture
    def csv_write(self, mcp):
        return mcp._tool_manager._tools["csv_write"].fn

    @pytest.fixture
    def csv_info(self, mcp):
        return mcp._tool_manager._tools["csv_info"].fn

    def test_csv_read_detects_duplicates(self, csv_read, tmp_path):
        csv_data = "name,age,name\nAlice,30,Alice2"
        csv_file = tmp_path / "duplicates.csv"
        csv_file.write_text(csv_data)

        with patch(
            "aden_tools.tools.csv_tool.csv_tool.get_secure_path",
            return_value=str(csv_file),
        ):
            result = csv_read(
                path="duplicates.csv", workspace_id="ws", agent_id="ag", session_id="s"
            )

        assert "error" in result
        assert "duplicate column names" in result["error"]
        assert "name" in result["duplicate_columns"]
        assert result["columns"] == ["name", "age", "name"]

    def test_csv_write_detects_duplicates(self, csv_write, tmp_path):
        csv_file = tmp_path / "write_duplicates.csv"

        with patch(
            "aden_tools.tools.csv_tool.csv_tool.get_secure_path",
            return_value=str(csv_file),
        ):
            result = csv_write(
                path="write_duplicates.csv",
                workspace_id="ws",
                agent_id="ag",
                session_id="s",
                columns=["id", "name", "id"],
                rows=[{"id": "1", "name": "test"}],
            )

        assert "error" in result
        assert "duplicate column names" in result["error"]
        assert not os.path.exists(csv_file)

    def test_csv_info_detects_duplicates(self, csv_info, tmp_path):
        csv_data = "id,value,id\n1,val,2"
        csv_file = tmp_path / "info_duplicates.csv"
        csv_file.write_text(csv_data)

        with patch(
            "aden_tools.tools.csv_tool.csv_tool.get_secure_path",
            return_value=str(csv_file),
        ):
            result = csv_info(
                path="info_duplicates.csv",
                workspace_id="ws",
                agent_id="ag",
                session_id="s",
            )

        assert "error" in result
        assert "duplicate column names" in result["error"]
        assert "id" in result["duplicate_columns"]
