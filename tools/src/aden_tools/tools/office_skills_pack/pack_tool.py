from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, cast

from fastmcp import FastMCP
from pydantic import BaseModel, Field

from aden_tools.tools.chart_tool.chart_tool import ChartSpec
from aden_tools.tools.excel_write_tool.excel_write_tool import WorkbookSpec
from aden_tools.tools.office_skills_pack.contracts import (
    CONTRACT_VERSION,
    ArtifactError,
    ArtifactResult,
)
from aden_tools.tools.office_skills_pack.limits import (
    MAX_CHART_POINTS,
    MAX_SHEET_ROWS,
    MAX_SLIDES,
)
from aden_tools.tools.office_skills_pack.logging_utils import tool_span
from aden_tools.tools.office_skills_pack.manifest_tool import ManifestSpec
from aden_tools.tools.powerpoint_tool.powerpoint_tool import DeckSpec
from aden_tools.tools.word_tool.word_tool import DocSpec


class ChartJob(BaseModel):
    path: str = Field(..., min_length=1, description="PNG output path relative to sandbox")
    chart: ChartSpec


class PackSpec(BaseModel):
    strict: bool = True
    dry_run: bool = False
    charts: List[ChartJob] = Field(default_factory=list)
    xlsx_path: Optional[str] = None
    pptx_path: Optional[str] = None
    docx_path: Optional[str] = None
    workbook: Optional[WorkbookSpec] = None
    deck: Optional[DeckSpec] = None
    doc: Optional[DocSpec] = None


def _apply_guardrails(spec: PackSpec) -> ArtifactError | None:
    for job in spec.charts:
        total_points = sum(min(len(s.x), len(s.y)) for s in job.chart.series)
        if total_points > MAX_CHART_POINTS and spec.strict:
            return ArtifactError(
                code="INVALID_SCHEMA",
                message="chart too large",
                details={"points": total_points, "max": MAX_CHART_POINTS},
            )

    if spec.deck and len(spec.deck.slides) > MAX_SLIDES and spec.strict:
        return ArtifactError(
            code="INVALID_SCHEMA",
            message="too many slides",
            details={"slides": len(spec.deck.slides), "max": MAX_SLIDES},
        )

    if spec.workbook:
        for sh in spec.workbook.sheets:
            if len(sh.rows) > MAX_SHEET_ROWS:
                if spec.strict:
                    return ArtifactError(
                        code="INVALID_SCHEMA",
                        message="too many rows",
                        details={"sheet": sh.name, "rows": len(sh.rows), "max": MAX_SHEET_ROWS},
                    )
                sh.rows = sh.rows[:MAX_SHEET_ROWS]
    return None


def register_tools(mcp: FastMCP) -> None:
    def _tool_fn(name: str) -> Callable[..., dict[str, Any]] | None:
        tool_obj = mcp._tool_manager._tools.get(name)
        if tool_obj is None:
            return None
        return cast(Callable[..., dict[str, Any]], getattr(tool_obj, "fn", None))

    @mcp.tool()
    def office_pack_generate(
        pack: dict[str, Any],
        workspace_id: str,
        agent_id: str,
        session_id: str,
    ) -> dict:
        """
        One-call generation: charts (png) + xlsx + pptx + docx.
        Returns ArtifactResult with manifest metadata.
        """
        with tool_span(
            "office_pack_generate",
            {
                "workspace_id": workspace_id,
                "agent_id": agent_id,
                "session_id": session_id,
            },
        ) as done:
            try:
                spec = PackSpec.model_validate(pack)
            except Exception as e:
                return done(
                    ArtifactResult(
                        success=False,
                        error=ArtifactError(code="INVALID_SCHEMA", message="Invalid pack schema", details=str(e)),
                    ).model_dump()
                )

            guardrail_error = _apply_guardrails(spec)
            if guardrail_error:
                return done(ArtifactResult(success=False, error=guardrail_error).model_dump())

            if spec.dry_run:
                return done(
                    ArtifactResult(
                        success=True,
                        metadata={
                            "dry_run": True,
                            "will_generate": {
                                "charts": [c.path for c in spec.charts],
                                "xlsx": spec.xlsx_path,
                                "pptx": spec.pptx_path,
                                "docx": spec.docx_path,
                            },
                        },
                    ).model_dump()
                )

            chart_png = _tool_fn("chart_render_png")
            xlsx = _tool_fn("excel_write")
            pptx = _tool_fn("powerpoint_generate")
            docx = _tool_fn("word_generate")

            if chart_png is None or xlsx is None or pptx is None or docx is None:
                return done(
                    ArtifactResult(
                        success=False,
                        error=ArtifactError(code="DEP_MISSING", message="Office pack tools not registered in MCP"),
                    ).model_dump()
                )

            for job in spec.charts:
                r = chart_png(
                    path=job.path,
                    chart=job.chart.model_dump(),
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    session_id=session_id,
                    strict=spec.strict,
                )
                if not r.get("success") and spec.strict:
                    err = r.get("error") or {}
                    return done(
                        ArtifactResult(
                            success=False,
                            error=ArtifactError(
                                code=err.get("code", "UNKNOWN"),
                                message=err.get("message", "chart generation failed"),
                                details=err.get("details"),
                            ),
                        ).model_dump()
                    )

            items: List[Dict[str, Any]] = []

            if spec.xlsx_path and spec.workbook is not None:
                r = xlsx(
                    path=spec.xlsx_path,
                    workbook=spec.workbook.model_dump(),
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    session_id=session_id,
                    strict=spec.strict,
                )
                if not r.get("success") and spec.strict:
                    return done(ArtifactResult(success=False, error=ArtifactError(**r["error"])).model_dump())
                if r.get("success"):
                    items.append(
                        {"tool": "excel_write", "output_path": spec.xlsx_path, "metadata": r.get("metadata", {})}
                    )

            if spec.pptx_path and spec.deck is not None:
                r = pptx(
                    path=spec.pptx_path,
                    deck=spec.deck.model_dump(),
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    session_id=session_id,
                    strict=spec.strict,
                )
                if not r.get("success") and spec.strict:
                    return done(ArtifactResult(success=False, error=ArtifactError(**r["error"])).model_dump())
                if r.get("success"):
                    items.append(
                        {
                            "tool": "powerpoint_generate",
                            "output_path": spec.pptx_path,
                            "metadata": r.get("metadata", {}),
                        }
                    )

            if spec.docx_path and spec.doc is not None:
                r = docx(
                    path=spec.docx_path,
                    doc=spec.doc.model_dump(),
                    workspace_id=workspace_id,
                    agent_id=agent_id,
                    session_id=session_id,
                    strict=spec.strict,
                )
                if not r.get("success") and spec.strict:
                    return done(ArtifactResult(success=False, error=ArtifactError(**r["error"])).model_dump())
                if r.get("success"):
                    items.append(
                        {"tool": "word_generate", "output_path": spec.docx_path, "metadata": r.get("metadata", {})}
                    )

            manifest = ManifestSpec.model_validate({"items": items})
            return done(
                ArtifactResult(
                    success=True,
                    contract_version=CONTRACT_VERSION,
                    metadata={"manifest": [i.model_dump() for i in manifest.items]},
                ).model_dump()
            )

    @mcp.tool()
    def office_pack_validate(
        pack: dict[str, Any],
        workspace_id: str,
        agent_id: str,
        session_id: str,
    ) -> dict:
        with tool_span(
            "office_pack_validate",
            {
                "workspace_id": workspace_id,
                "agent_id": agent_id,
                "session_id": session_id,
            },
        ) as done:
            try:
                spec = PackSpec.model_validate(pack)
            except Exception as e:
                return done(
                    ArtifactResult(
                        success=False,
                        error=ArtifactError(code="INVALID_SCHEMA", message="Invalid pack schema", details=str(e)),
                    ).model_dump()
                )

            guardrail_error = _apply_guardrails(spec)
            if guardrail_error:
                return done(ArtifactResult(success=False, error=guardrail_error).model_dump())

            return done(
                ArtifactResult(
                    success=True,
                    metadata={
                        "valid": True,
                        "dry_run": True,
                        "will_generate": {
                            "charts": [c.path for c in spec.charts],
                            "xlsx": spec.xlsx_path,
                            "pptx": spec.pptx_path,
                            "docx": spec.docx_path,
                        },
                    },
                ).model_dump()
            )
