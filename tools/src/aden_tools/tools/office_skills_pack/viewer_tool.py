from __future__ import annotations

from typing import Any, List

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from aden_tools.tools.office_skills_pack.contracts import CONTRACT_VERSION


class ViewerItem(BaseModel):
    tool: str
    output_path: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ViewerSpec(BaseModel):
    title: str = "Office Pack Output"
    items: List[ViewerItem] = Field(default_factory=list)


def register_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def office_pack_view_markdown(title: str, items: list[dict[str, Any]]) -> dict:
        spec = ViewerSpec.model_validate({"title": title, "items": items})
        lines = [f"# {spec.title}", "", f"Contract: `{CONTRACT_VERSION}`", ""]
        for it in spec.items:
            lines.append(f"- **{it.tool}** -> `{it.output_path}`")
            if it.metadata:
                lines.append(f"  - metadata: `{it.metadata}`")
        return {"contract_version": CONTRACT_VERSION, "markdown": "\n".join(lines)}
