from pathlib import Path
from unittest.mock import patch

from fastmcp import FastMCP

from aden_tools.tools.office_skills_pack.register import register_office_skills_pack


def test_validate_and_build_spec(tmp_path: Path):
    with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
        mcp = FastMCP("validate-builder")
        register_office_skills_pack(mcp)

        build = mcp._tool_manager._tools["office_pack_build_spec"].fn
        validate = mcp._tool_manager._tools["office_pack_validate"].fn

        r = build({"title": "T", "metrics": [{"ticker": "AAPL", "ret": 0.01, "drawdown": -0.02}]})
        assert "pack" in r

        v = validate(r["pack"], workspace_id="w", agent_id="a", session_id="s")
        assert v["success"] is True
        assert v["metadata"]["valid"] is True
