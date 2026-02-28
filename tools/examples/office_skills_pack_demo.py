"""
Office Skills Pack demo:
Generates XLSX + PPTX + DOCX into the session sandbox.

Run:
  - from repo root:  python tools/examples/office_skills_pack_demo.py
  - from tools/:     python examples/office_skills_pack_demo.py
"""
from aden_tools.tools.mcp_helpers import get_tool_fn
from aden_tools.tools.office_skills_pack import register_office_skills_pack
from fastmcp import FastMCP

WORKSPACE_ID = "demo-ws"
AGENT_ID = "demo-agent"
SESSION_ID = "demo-session"


def main():
    mcp = FastMCP("office-skills-demo")
    register_office_skills_pack(mcp)

    # NOTE: This still accesses the registered function, but not via private _tool_manager internals if MCP exposes a public method.
    # If FastMCP does NOT expose a public getter, keep this for now but we can swap to public API later.

    xlsx = get_tool_fn(mcp, "excel_write")
    pptx = get_tool_fn(mcp, "powerpoint_generate")
    docx = get_tool_fn(mcp, "word_generate")
    chart_png = get_tool_fn(mcp, "chart_render_png")
    
    metrics = [
        {"Ticker": "AAPL", "Return": 0.0123, "Drawdown": -0.034},
        {"Ticker": "MSFT", "Return": 0.0040, "Drawdown": -0.021},
    ]

    chart_png(
        path="out/aapl_msft.png",
        chart={
            "title": "AAPL vs MSFT (synthetic)",
            "x_label": "Day",
            "y_label": "Price",
            "series": [
                {"name": "AAPL", "x": [1, 2, 3, 4, 5], "y": [190, 191, 192, 191, 193]},
                {"name": "MSFT", "x": [1, 2, 3, 4, 5], "y": [410, 412, 411, 413, 414]},
            ],
        },
        workspace_id=WORKSPACE_ID,
        agent_id=AGENT_ID,
        session_id=SESSION_ID,
    )

    xlsx(
        path="out/weekly_report.xlsx",
        workbook={
            "sheets": [
                {
                    "name": "Summary",
                    "columns": ["Ticker", "Return", "Drawdown"],
                    "rows": [[m["Ticker"], m["Return"], m["Drawdown"]] for m in metrics],
                    "freeze_panes": "A2",
                    "number_formats": {"Return": "0.00%", "Drawdown": "0.00%"},
                },
                {
                    "name": "Charts",
                    "columns": ["Chart"],
                    "rows": [["AAPL vs MSFT"]],
                    "freeze_panes": "A2",
                    "images": [{"path": "out/aapl_msft.png", "cell": "A3", "width": 600}],
                },
            ]
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
                {"title": "Chart", "bullets": ["Synthetic price chart"], "image_paths": ["out/aapl_msft.png"], "charts": []},
                
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

    print("Generated: out/weekly_report.xlsx, out/weekly_report.pptx, out/weekly_report.docx (in sandbox)")


if __name__ == "__main__":
    main()
