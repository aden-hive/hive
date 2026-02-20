from __future__ import annotations

import os
from typing import Any, List, Optional

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from aden_tools.tools.office_skills_pack.contracts import ArtifactError, ArtifactResult
from ..file_system_toolkits.security import get_secure_path


class SeriesSpec(BaseModel):
    name: str = Field(..., min_length=1)
    x: List[float] = Field(..., min_length=1)
    y: List[float] = Field(..., min_length=1)


class ChartSpec(BaseModel):
    title: str = Field(..., min_length=1)
    x_label: str = Field(default="")
    y_label: str = Field(default="")
    series: List[SeriesSpec] = Field(..., min_length=1)


def register_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def chart_render_png(
        path: str,
        chart: dict[str, Any],
        workspace_id: str,
        agent_id: str,
        session_id: str,
    ) -> dict:
        """
        Render a simple multi-series line chart into a PNG (schema-first) saved into the session sandbox.
        """
        if not path.lower().endswith(".png"):
            return ArtifactResult(
                success=False,
                error=ArtifactError(code="INVALID_PATH", message="path must end with .png"),
            ).model_dump()

        try:
            spec = ChartSpec.model_validate(chart)
        except Exception as e:
            return ArtifactResult(
                success=False,
                error=ArtifactError(code="INVALID_SCHEMA", message="Invalid chart schema", details=str(e)),
            ).model_dump()

        try:
            import matplotlib.pyplot as plt
        except ImportError:
            return ArtifactResult(
                success=False,
                error=ArtifactError(
                    code="DEP_MISSING",
                    message="matplotlib not installed",
                    details="Install with: pip install -e '.[charts]' (from tools/)",
                ),
            ).model_dump()

        try:
            out_path = get_secure_path(path, workspace_id, agent_id, session_id)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)

            plt.figure()
            for s in spec.series:
                # handle mismatched lengths safely
                n = min(len(s.x), len(s.y))
                plt.plot(s.x[:n], s.y[:n], label=s.name)

            plt.title(spec.title)
            if spec.x_label:
                plt.xlabel(spec.x_label)
            if spec.y_label:
                plt.ylabel(spec.y_label)

            if len(spec.series) > 1:
                plt.legend()

            plt.tight_layout()
            plt.savefig(out_path, dpi=150)
            plt.close()

            return ArtifactResult(
                success=True,
                output_path=path,
                metadata={"series": len(spec.series)},
            ).model_dump()

        except Exception as e:
            return ArtifactResult(
                success=False,
                error=ArtifactError(code="IO_ERROR", message="Failed to write png", details=str(e)),
            ).model_dump()
