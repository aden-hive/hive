from __future__ import annotations

import os
from math import ceil
from typing import Any, List, Optional

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from aden_tools.tools.office_skills_pack.contracts import ArtifactError, ArtifactResult
from aden_tools.tools.office_skills_pack.hash_utils import sha256_file
from aden_tools.tools.office_skills_pack.limits import MAX_CHART_POINTS
from aden_tools.tools.office_skills_pack.logging_utils import tool_span
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
        strict: bool = True,
    ) -> dict:
        """
        Render a simple multi-series line chart into a PNG (schema-first) saved into the session sandbox.
        """
        with tool_span(
            "chart_render_png",
            {"workspace_id": workspace_id, "agent_id": agent_id, "session_id": session_id, "output_path": path},
        ) as done:
            if not path.lower().endswith(".png"):
                return done(
                    ArtifactResult(
                        success=False,
                        error=ArtifactError(code="INVALID_PATH", message="path must end with .png"),
                    ).model_dump()
                )

            try:
                spec = ChartSpec.model_validate(chart)
            except Exception as e:
                return done(
                    ArtifactResult(
                        success=False,
                        error=ArtifactError(code="INVALID_SCHEMA", message="Invalid chart schema", details=str(e)),
                    ).model_dump()
                )

            try:
                import matplotlib

                matplotlib.use("Agg")
                import matplotlib.pyplot as plt
            except ImportError:
                return done(
                    ArtifactResult(
                        success=False,
                        error=ArtifactError(
                            code="DEP_MISSING",
                            message="matplotlib not installed",
                            details="Install with: pip install -e '.[charts]' (from tools/)",
                        ),
                    ).model_dump()
                )

            try:
                total_points = sum(min(len(s.x), len(s.y)) for s in spec.series)
                downsample_step = 1
                if total_points > MAX_CHART_POINTS:
                    if strict:
                        return done(
                            ArtifactResult(
                                success=False,
                                error=ArtifactError(
                                    code="INVALID_SCHEMA",
                                    message="chart too large",
                                    details={"points": total_points, "max": MAX_CHART_POINTS},
                                ),
                            ).model_dump()
                        )
                    downsample_step = max(2, ceil(total_points / MAX_CHART_POINTS))

                out_path = get_secure_path(path, workspace_id, agent_id, session_id)
                os.makedirs(os.path.dirname(out_path), exist_ok=True)

                plt.figure()
                for s in spec.series:
                    n = min(len(s.x), len(s.y))
                    x_vals = s.x[:n]
                    y_vals = s.y[:n]
                    if downsample_step > 1:
                        x_vals = x_vals[::downsample_step]
                        y_vals = y_vals[::downsample_step]
                    plt.plot(x_vals, y_vals, label=s.name)

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
                digest = sha256_file(out_path)

                return done(
                    ArtifactResult(
                        success=True,
                        output_path=path,
                        metadata={"series": len(spec.series), "sha256": digest},
                    ).model_dump()
                )

            except Exception as e:
                return done(
                    ArtifactResult(
                        success=False,
                        error=ArtifactError(code="IO_ERROR", message="Failed to write png", details=str(e)),
                    ).model_dump()
                )
