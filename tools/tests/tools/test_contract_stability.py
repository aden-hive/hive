from pathlib import Path
from unittest.mock import patch

from fastmcp import FastMCP

from aden_tools.tools.office_skills_pack.register import register_office_skills_pack


def test_contract_version_present(tmp_path: Path):
    with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
        mcp = FastMCP("contract-stability")
        register_office_skills_pack(mcp)
        pack = mcp._tool_manager._tools["office_pack_generate"].fn

        res = pack(pack={"strict": True}, workspace_id="w", agent_id="a", session_id="s")
        assert "contract_version" in res


def test_error_contract_fields(tmp_path: Path):
    with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
        mcp = FastMCP("contract-stability-error")
        register_office_skills_pack(mcp)
        xlsx = mcp._tool_manager._tools["excel_write"].fn
        res = xlsx(
            path="out/bad.txt",
            workbook={"sheets": [{"name": "S", "columns": ["A"], "rows": [[1]]}]},
            workspace_id="w",
            agent_id="a",
            session_id="s",
            strict=True,
        )
        assert res["success"] is False
        assert "error" in res
        err = res["error"]
        assert "code" in err
        assert "message" in err
        assert "details" in err
