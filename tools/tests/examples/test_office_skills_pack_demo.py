from pathlib import Path
from unittest.mock import patch

from fastmcp import FastMCP

from aden_tools.tools.excel_write_tool.excel_write_tool import register_tools as register_xlsx
from aden_tools.tools.powerpoint_tool.powerpoint_tool import register_tools as register_ppt
from aden_tools.tools.word_tool.word_tool import register_tools as register_word

from aden_tools.tools.file_system_toolkits.security import get_secure_path
from aden_tools.tools.mcp_helpers import get_tool_fn



def test_office_skills_pack_demo_smoke(tmp_path: Path):
    # Redirect sandbox to tmp (Windows-safe)
    with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
        mcp = FastMCP("office-skills-demo-test")
        register_xlsx(mcp)
        register_ppt(mcp)
        register_word(mcp)

        xlsx = get_tool_fn(mcp, "excel_write")
        pptx = get_tool_fn(mcp, "powerpoint_generate")
        docx = get_tool_fn(mcp, "word_generate")

        metrics = [
            {"Ticker": "AAPL", "Return": 0.0123, "Drawdown": -0.034},
            {"Ticker": "MSFT", "Return": 0.0040, "Drawdown": -0.021},
        ]

        res_x = xlsx(
            path="out/weekly_report.xlsx",
            workbook={
                "sheets": [{
                    "name": "Summary",
                    "columns": ["Ticker", "Return", "Drawdown"],
                    "rows": [[m["Ticker"], m["Return"], m["Drawdown"]] for m in metrics],
                    "freeze_panes": "A2",
                    "number_formats": {"Return": "0.00%", "Drawdown": "0.00%"},
                }]
            },
            workspace_id="demo-ws",
            agent_id="demo-agent",
            session_id="demo-session",
        )
        assert res_x.get("success") is True, res_x

        res_p = pptx(
            path="out/weekly_report.pptx",
            deck={
                "title": "Weekly Market Brief",
                "slides": [
                    {"title": "Summary", "bullets": ["AAPL outperformed", "MSFT stable"], "image_paths": []},
                ],
            },
            workspace_id="demo-ws",
            agent_id="demo-agent",
            session_id="demo-session",
        )
        assert res_p.get("success") is True, res_p  # <- this will show the real error if any

        res_d = docx(
            path="out/weekly_report.docx",
            doc={
                "title": "Weekly Market Report",
                "sections": [
                    {"heading": "Executive Summary", "paragraphs": ["Auto-generated report."], "bullets": []},
                ],
            },
            workspace_id="demo-ws",
            agent_id="demo-agent",
            session_id="demo-session",
        )
        assert res_d.get("success") is True, res_d

        # Resolve expected outputs via the same sandbox function (most correct)
        x_abs = get_secure_path("out/weekly_report.xlsx", "demo-ws", "demo-agent", "demo-session")
        p_abs = get_secure_path("out/weekly_report.pptx", "demo-ws", "demo-agent", "demo-session")
        d_abs = get_secure_path("out/weekly_report.docx", "demo-ws", "demo-agent", "demo-session")

        assert Path(x_abs).exists()
        assert Path(p_abs).exists()
        assert Path(d_abs).exists()

        assert Path(x_abs).stat().st_size > 0
        assert Path(p_abs).stat().st_size > 0
        assert Path(d_abs).stat().st_size > 0
