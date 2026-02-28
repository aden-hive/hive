from __future__ import annotations

from typing import Any, List

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from aden_tools.tools.office_skills_pack.contracts import CONTRACT_VERSION


class ManifestItem(BaseModel):
    tool: str
    output_path: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ManifestSpec(BaseModel):
    items: List[ManifestItem] = Field(default_factory=list)


def register_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def office_skills_manifest(items: list[dict[str, Any]]) -> dict:
        """
        Return a normalized manifest for generated artifacts.
        """
        spec = ManifestSpec.model_validate({"items": items})
        return {
            "contract_version": CONTRACT_VERSION,
            "items": [i.model_dump() for i in spec.items],
        }
