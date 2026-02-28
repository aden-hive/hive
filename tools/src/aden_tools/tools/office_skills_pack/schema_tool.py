from __future__ import annotations

from fastmcp import FastMCP

from aden_tools.tools.chart_tool.chart_tool import ChartSpec
from aden_tools.tools.excel_write_tool.excel_write_tool import WorkbookSpec
from aden_tools.tools.office_skills_pack.contracts import CONTRACT_VERSION
from aden_tools.tools.office_skills_pack.pack_tool import PackSpec
from aden_tools.tools.powerpoint_tool.powerpoint_tool import DeckSpec
from aden_tools.tools.word_tool.word_tool import DocSpec

SUPPORTED_TOOL_NAMES = ["chart", "excel", "powerpoint", "word", "pack"]


def register_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def office_skills_schema(tool_name: str) -> dict:
        """
        Return JSON schema for Office Skills Pack input specs.
        tool_name: one of ['chart', 'excel', 'powerpoint', 'word', 'pack']
        """
        name = tool_name.strip().lower()
        if name == "chart":
            return {
                "contract_version": CONTRACT_VERSION,
                "tool": "chart",
                "schema": ChartSpec.model_json_schema(),
            }
        if name == "excel":
            return {
                "contract_version": CONTRACT_VERSION,
                "tool": "excel",
                "schema": WorkbookSpec.model_json_schema(),
            }
        if name == "powerpoint":
            return {
                "contract_version": CONTRACT_VERSION,
                "tool": "powerpoint",
                "schema": DeckSpec.model_json_schema(),
            }
        if name == "word":
            return {
                "contract_version": CONTRACT_VERSION,
                "tool": "word",
                "schema": DocSpec.model_json_schema(),
            }
        if name == "pack":
            return {
                "contract_version": CONTRACT_VERSION,
                "tool": "pack",
                "schema": PackSpec.model_json_schema(),
            }
        return {
            "contract_version": CONTRACT_VERSION,
            "error": "unknown tool_name",
            "supported": SUPPORTED_TOOL_NAMES,
        }
