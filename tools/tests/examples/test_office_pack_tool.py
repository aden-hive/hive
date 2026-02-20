import json
from pathlib import Path
from unittest.mock import patch

from fastmcp import FastMCP

from aden_tools.tools.file_system_toolkits.security import get_secure_path
from aden_tools.tools.office_skills_pack.register import register_office_skills_pack


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def test_office_pack_generate_strict_success(tmp_path: Path):
    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "office_skills_pack"
    deck = _load(fixtures / "deck.json")
    wb = _load(fixtures / "workbook.json")
    doc = _load(fixtures / "doc.json")

    with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
        mcp = FastMCP("pack-test")
        register_office_skills_pack(mcp)
        pack = mcp._tool_manager._tools["office_pack_generate"].fn

        res = pack(
            pack={
                "strict": True,
                "charts": [
                    {
                        "path": "out/chart.png",
                        "chart": {
                            "title": "T",
                            "x_label": "x",
                            "y_label": "y",
                            "series": [{"name": "s", "x": [1, 2], "y": [1, 2]}],
                        },
                    }
                ],
                "xlsx_path": "out/pack.xlsx",
                "pptx_path": "out/pack.pptx",
                "docx_path": "out/pack.docx",
                "workbook": wb,
                "deck": deck,
                "doc": doc,
            },
            workspace_id="w",
            agent_id="a",
            session_id="s",
        )

        assert res["success"] is True, res
        assert "manifest" in res["metadata"]
        assert len(res["metadata"]["manifest"]) == 3

        assert Path(get_secure_path("out/pack.xlsx", "w", "a", "s")).exists()
        assert Path(get_secure_path("out/pack.pptx", "w", "a", "s")).exists()
        assert Path(get_secure_path("out/pack.docx", "w", "a", "s")).exists()


def test_office_pack_generate_nonstrict_skips_missing_image(tmp_path: Path):
    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "office_skills_pack"
    deck = _load(fixtures / "deck.json")
    deck["slides"][1]["image_paths"] = ["out/does_not_exist.png"]

    with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
        mcp = FastMCP("pack-test2")
        register_office_skills_pack(mcp)
        pack = mcp._tool_manager._tools["office_pack_generate"].fn

        res = pack(
            pack={
                "strict": False,
                "pptx_path": "out/pack2.pptx",
                "deck": deck,
            },
            workspace_id="w",
            agent_id="a",
            session_id="s",
        )
        assert res["success"] is True, res
        assert len(res["metadata"]["manifest"]) == 1
        assert Path(get_secure_path("out/pack2.pptx", "w", "a", "s")).exists()


def test_office_pack_generate_strict_fails_missing_image(tmp_path: Path):
    fixtures = Path(__file__).resolve().parents[1] / "fixtures" / "office_skills_pack"
    deck = _load(fixtures / "deck.json")
    deck["slides"][1]["image_paths"] = ["out/does_not_exist.png"]

    with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
        mcp = FastMCP("pack-test3")
        register_office_skills_pack(mcp)
        pack = mcp._tool_manager._tools["office_pack_generate"].fn

        res = pack(
            pack={
                "strict": True,
                "pptx_path": "out/pack3.pptx",
                "deck": deck,
            },
            workspace_id="w",
            agent_id="a",
            session_id="s",
        )
        assert res["success"] is False, res


def test_office_pack_validate_reports_valid(tmp_path: Path):
    with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
        mcp = FastMCP("pack-validate")
        register_office_skills_pack(mcp)
        validate = mcp._tool_manager._tools["office_pack_validate"].fn

        res = validate(
            pack={
                "strict": True,
                "xlsx_path": "out/ok.xlsx",
                "workbook": {"sheets": [{"name": "S", "columns": ["A"], "rows": [[1]]}]},
            },
            workspace_id="w",
            agent_id="a",
            session_id="s",
        )
        assert res["success"] is True, res
        assert res["metadata"]["valid"] is True
