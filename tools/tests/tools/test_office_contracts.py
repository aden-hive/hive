from pathlib import Path
from unittest.mock import patch

from fastmcp import FastMCP

from aden_tools.tools.powerpoint_tool.powerpoint_tool import register_tools as register_ppt


def test_contract_error_codes(tmp_path: Path):
    with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
        mcp = FastMCP("contract-test")
        register_ppt(mcp)
        pptx = mcp._tool_manager._tools["powerpoint_generate"].fn

        # invalid schema: slides missing
        res = pptx(
            path="out/x.pptx",
            deck={"title": "Bad"},  # missing slides
            workspace_id="w",
            agent_id="a",
            session_id="s",
        )

        assert res["success"] is False
        assert res["error"]["code"] == "INVALID_SCHEMA"
        assert "contract_version" in res
