from fastmcp import FastMCP

from aden_tools.tools.mcp_helpers import get_tool_fn
from aden_tools.tools.office_skills_pack import register_office_skills_pack

WORKSPACE_ID = "demo-ws"
AGENT_ID = "demo-agent"
SESSION_ID = "demo-session"


def drawdown(prices):
    peak = prices[0]
    dd = 0.0
    for p in prices:
        peak = max(peak, p)
        dd = min(dd, (p - peak) / peak)
    return dd


def main():
    mcp = FastMCP("finance-example")
    register_office_skills_pack(mcp)

    chart_png = get_tool_fn(mcp, "chart_render_png")
    xlsx = get_tool_fn(mcp, "excel_write")
    pptx = get_tool_fn(mcp, "powerpoint_generate")
    docx = get_tool_fn(mcp, "word_generate")

    days = [1, 2, 3, 4, 5]
    aapl = [190, 191, 192, 191, 193]
    msft = [410, 412, 411, 413, 414]

    metrics = [
        {"Ticker": "AAPL", "Return": (aapl[-1] / aapl[0] - 1), "Drawdown": drawdown(aapl)},
        {"Ticker": "MSFT", "Return": (msft[-1] / msft[0] - 1), "Drawdown": drawdown(msft)},
    ]

    chart_png(
        path="out/aapl_msft.png",
        chart={
            "title": "AAPL vs MSFT",
            "x_label": "Day",
            "y_label": "Price",
            "series": [
                {"name": "AAPL", "x": days, "y": aapl},
                {"name": "MSFT", "x": days, "y": msft},
            ],
        },
        workspace_id=WORKSPACE_ID,
        agent_id=AGENT_ID,
        session_id=SESSION_ID,
    )

    xlsx(
        path="out/finance_report.xlsx",
        workbook={
            "sheets": [
                {
                    "name": "Summary",
                    "columns": ["Ticker", "Return", "Drawdown"],
                    "rows": [[m["Ticker"], m["Return"], m["Drawdown"]] for m in metrics],
                    "number_formats": {"Return": "0.00%", "Drawdown": "0.00%"},
                    "freeze_panes": "A2",
                },
                {
                    "name": "Charts",
                    "columns": ["Chart"],
                    "rows": [["AAPL vs MSFT"]],
                    "images": [{"path": "out/aapl_msft.png", "cell": "A3", "width": 600}],
                },
            ]
        },
        workspace_id=WORKSPACE_ID,
        agent_id=AGENT_ID,
        session_id=SESSION_ID,
    )

    pptx(
        path="out/finance_report.pptx",
        deck={
            "title": "Finance Brief",
            "slides": [
                {
                    "title": "Summary",
                    "bullets": [
                        f"{m['Ticker']}: Return {m['Return']:.2%}, DD {m['Drawdown']:.2%}"
                        for m in metrics
                    ],
                    "image_paths": [],
                    "charts": [],
                },
                {
                    "title": "Chart",
                    "bullets": ["Price series"],
                    "image_paths": ["out/aapl_msft.png"],
                    "charts": [],
                },
            ],
        },
        workspace_id=WORKSPACE_ID,
        agent_id=AGENT_ID,
        session_id=SESSION_ID,
    )

    docx(
        path="out/finance_report.docx",
        doc={
            "title": "Finance Report",
            "sections": [
                {
                    "heading": "Executive Summary",
                    "paragraphs": ["Auto-generated finance artifacts (local-only MVP)."],
                    "bullets": [],
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

    print("Generated finance_report.xlsx/.pptx/.docx (in sandbox)")


if __name__ == "__main__":
    main()
