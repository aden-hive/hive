"""
Office Skills Pack demo:
Generates XLSX + PPTX + DOCX into the session sandbox.

Run:
  - from repo root:  python tools/examples/office_skills_pack_demo.py
  - from tools/:     python examples/office_skills_pack_demo.py
"""

from aden_tools.tools.excel_write_tool.excel_write_tool import register_tools as register_xlsx
from aden_tools.tools.powerpoint_tool.powerpoint_tool import register_tools as register_ppt
from aden_tools.tools.word_tool.word_tool import register_tools as register_word
from aden_tools.tools.testing_utils import get_tool_fn
from fastmcp import FastMCP

WORKSPACE_ID = "demo-ws"
AGENT_ID = "demo-agent"
SESSION_ID = "demo-session"


def main():
    mcp = FastMCP("office-skills-demo")
    register_xlsx(mcp)
    register_ppt(mcp)
    register_word(mcp)

    # NOTE: This still accesses the registered function, but not via private _tool_manager internals if MCP exposes a public method.
    # If FastMCP does NOT expose a public getter, keep this for now but we can swap to public API later.
    xlsx = mcp._tool_manager._tools["excel_write"].fn
    pptx = mcp._tool_manager._tools["powerpoint_generate"].fn
    docx = mcp._tool_manager._tools["word_generate"].fn

    metrics = [
        {"Ticker": "AAPL", "Return": 0.0123, "Drawdown": -0.034},
        {"Ticker": "MSFT", "Return": 0.0040, "Drawdown": -0.021},
    ]

    xlsx(
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
        workspace_id=WORKSPACE_ID,
        agent_id=AGENT_ID,
        session_id=SESSION_ID,
    )

    pptx(
        path="out/weekly_report.pptx",
        deck={
            "title": "Weekly Market Brief",
            "slides": [
                {"title": "Summary", "bullets": ["AAPL outperformed", "MSFT stable"], "image_paths": []},
                {"title": "Key Metrics", "bullets": [f"{m['Ticker']}: Return {m['Return']:.2%}, DD {m['Drawdown']:.2%}" for m in metrics], "image_paths": []},
            ],
        },
        workspace_id=WORKSPACE_ID,
        agent_id=AGENT_ID,
        session_id=SESSION_ID,
    )

    docx(
        path="out/weekly_report.docx",
        doc={
            "title": "Weekly Market Report",
            "sections": [
                {
                    "heading": "Executive Summary",
                    "paragraphs": ["Auto-generated report (schema-first, local-only MVP)."],
                    "bullets": ["XLSX + PPTX + DOCX generated locally", "Saved into session sandbox"],
                },
                {
                    "heading": "Metrics",
                    "paragraphs": [],
                    "bullets": [],
                    "table": {
                        "columns": ["Ticker", "Return", "Drawdown"],
                        "rows": [[m["Ticker"], m["Return"], m["Drawdown"]] for m in metrics],
                    },
                },
            ],
        },
        workspace_id=WORKSPACE_ID,
        agent_id=AGENT_ID,
        session_id=SESSION_ID,
    )

    print("✅ Generated: out/weekly_report.xlsx, out/weekly_report.pptx, out/weekly_report.docx (in sandbox)")


if __name__ == "__main__":
    main()
