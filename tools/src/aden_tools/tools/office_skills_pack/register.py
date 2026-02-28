from fastmcp import FastMCP

from aden_tools.tools.chart_tool.chart_tool import register_tools as register_charts
from aden_tools.tools.excel_write_tool.excel_write_tool import (
    register_tools as register_excel_write,
)
from aden_tools.tools.office_skills_pack.manifest_tool import (
    register_tools as register_manifest,
)
from aden_tools.tools.office_skills_pack.examples_tool import register_tools as register_examples
from aden_tools.tools.office_skills_pack.list_tool import register_tools as register_list_outputs
from aden_tools.tools.office_skills_pack.pack_tool import register_tools as register_pack_tool
from aden_tools.tools.office_skills_pack.schema_tool import register_tools as register_schema
from aden_tools.tools.office_skills_pack.spec_builder_tool import register_tools as register_spec_builder
from aden_tools.tools.office_skills_pack.viewer_tool import register_tools as register_viewer
from aden_tools.tools.powerpoint_tool.powerpoint_tool import (
    register_tools as register_powerpoint,
)
from aden_tools.tools.word_tool.word_tool import register_tools as register_word


def register_office_skills_pack(mcp: FastMCP) -> None:
    register_charts(mcp)
    register_excel_write(mcp)
    register_powerpoint(mcp)
    register_word(mcp)
    register_schema(mcp)
    register_manifest(mcp)
    register_pack_tool(mcp)
    register_viewer(mcp)
    register_list_outputs(mcp)
    register_examples(mcp)
    register_spec_builder(mcp)
