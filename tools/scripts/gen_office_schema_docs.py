from __future__ import annotations

import json
from pathlib import Path

from fastmcp import FastMCP

from aden_tools.tools.mcp_helpers import get_tool_fn
from aden_tools.tools.office_skills_pack import register_office_skills_pack

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tools/src/aden_tools/tools/office_skills_pack/SCHEMAS.md"


def main() -> None:
    mcp = FastMCP("schema-docs")
    register_office_skills_pack(mcp)

    schema = get_tool_fn(mcp, "office_skills_schema")
    examples = get_tool_fn(mcp, "office_skills_schema_examples")

    ex = examples()
    tools = ["chart", "excel", "powerpoint", "word", "pack"]

    lines = ["# Office Skills Pack Schemas", "", "Generated from live Pydantic models.", ""]

    for tool_name in tools:
        s = schema(tool_name=tool_name)
        lines.append(f"## {tool_name}")
        lines.append("")
        lines.append("### Schema")
        lines.append("```json")
        lines.append(json.dumps(s["schema"], indent=2))
        lines.append("```")
        lines.append("")
        lines.append("### Minimal example")
        lines.append("```json")
        lines.append(json.dumps(ex[tool_name], indent=2))
        lines.append("```")
        lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
