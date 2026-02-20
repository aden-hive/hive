from __future__ import annotations

from typing import Any, List

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from aden_tools.tools.office_skills_pack.contracts import CONTRACT_VERSION


class MetricRow(BaseModel):
    ticker: str
    ret: float
    drawdown: float


class SpecBuilderInput(BaseModel):
    title: str = "Finance Brief"
    metrics: List[MetricRow] = Field(default_factory=list)


def register_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def office_pack_build_spec(data: dict[str, Any]) -> dict:
        spec = SpecBuilderInput.model_validate(data)

        pack = {
            "strict": True,
            "charts": [],
            "xlsx_path": "out/report.xlsx",
            "pptx_path": "out/report.pptx",
            "docx_path": "out/report.docx",
            "workbook": {
                "sheets": [
                    {
                        "name": "Summary",
                        "columns": ["Ticker", "Return", "Drawdown"],
                        "rows": [[m.ticker, m.ret, m.drawdown] for m in spec.metrics],
                        "number_formats": {"Return": "0.00%", "Drawdown": "0.00%"},
                        "freeze_panes": "A2",
                        "auto_filter": True,
                        "header_fill": True,
                    }
                ]
            },
            "deck": {
                "title": spec.title,
                "slides": [
                    {
                        "title": "Summary",
                        "bullets": [f"{m.ticker}: Return {m.ret:.2%}, DD {m.drawdown:.2%}" for m in spec.metrics],
                        "image_paths": [],
                        "charts": [],
                    }
                ],
            },
            "doc": {
                "title": spec.title,
                "sections": [
                    {
                        "heading": "Executive Summary",
                        "paragraphs": ["Auto-generated from metrics."],
                        "bullets": [],
                    }
                ],
            },
        }

        return {"contract_version": CONTRACT_VERSION, "pack": pack}
