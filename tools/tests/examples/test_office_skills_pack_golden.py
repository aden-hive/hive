import json
from pathlib import Path
from unittest.mock import patch

from fastmcp import FastMCP

from aden_tools.tools.chart_tool.chart_tool import register_tools as register_chart
from aden_tools.tools.excel_write_tool.excel_write_tool import register_tools as register_xlsx
from aden_tools.tools.file_system_toolkits.security import get_secure_path
from aden_tools.tools.powerpoint_tool.powerpoint_tool import register_tools as register_ppt
from aden_tools.tools.word_tool.word_tool import register_tools as register_word


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def test_office_skills_pack_golden(tmp_path: Path):
    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "office_skills_pack"
    deck = _load(fixtures / "deck.json")
    wb = _load(fixtures / "workbook.json")
    doc = _load(fixtures / "doc.json")

    with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
        mcp = FastMCP("golden")
        register_chart(mcp)
        register_xlsx(mcp)
        register_ppt(mcp)
        register_word(mcp)

        chart_png = mcp._tool_manager._tools["chart_render_png"].fn
        xlsx = mcp._tool_manager._tools["excel_write"].fn
        pptx = mcp._tool_manager._tools["powerpoint_generate"].fn
        docx = mcp._tool_manager._tools["word_generate"].fn

        r = chart_png(
            path="out/chart.png",
            chart={
                "title": "T",
                "x_label": "x",
                "y_label": "y",
                "series": [{"name": "s", "x": [1, 2, 3], "y": [1, 4, 9]}],
            },
            workspace_id="w",
            agent_id="a",
            session_id="s",
        )
        assert r["success"] is True, r

        rx = xlsx(path="out/golden.xlsx", workbook=wb, workspace_id="w", agent_id="a", session_id="s")
        rp = pptx(path="out/golden.pptx", deck=deck, workspace_id="w", agent_id="a", session_id="s")
        rd = docx(path="out/golden.docx", doc=doc, workspace_id="w", agent_id="a", session_id="s")

        assert rx["success"] is True, rx
        assert rp["success"] is True, rp
        assert rd["success"] is True, rd

        assert Path(get_secure_path("out/golden.xlsx", "w", "a", "s")).exists()
        assert Path(get_secure_path("out/golden.pptx", "w", "a", "s")).exists()
        assert Path(get_secure_path("out/golden.docx", "w", "a", "s")).exists()
