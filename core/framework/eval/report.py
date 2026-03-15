"""
EvalCaseResult and EvalReport — output schema for the eval system.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ScoreDimension(BaseModel):
    """Score on a single dimension."""

    name: str
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    detail: str = ""


class EvalCaseResult(BaseModel):
    """Result for a single eval case."""

    __test__ = False

    case_id: str
    passed: bool
    score: float = Field(ge=0.0, le=1.0, description="Weighted composite score 0-1")

    # Raw agent output
    agent_output: Any = None
    agent_error: str | None = None

    # Dimension scores
    dimensions: list[ScoreDimension] = Field(default_factory=list)

    # Performance metrics
    latency_ms: int = 0
    estimated_cost_usd: float = 0.0
    tools_called: list[str] = Field(default_factory=list)
    nodes_visited: list[str] = Field(default_factory=list)

    # LLM judge result
    llm_judge_passed: bool | None = None
    llm_judge_explanation: str | None = None

    timestamp: datetime = Field(default_factory=datetime.now)

    model_config = {"extra": "allow"}

    def summary(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "score": round(self.score, 3),
            "latency_ms": self.latency_ms,
            "cost_usd": round(self.estimated_cost_usd, 6),
            "tools_called": self.tools_called,
            "failed_dimensions": [d.name for d in self.dimensions if not d.passed],
        }


class EvalReport(BaseModel):
    """Aggregate report for a full eval suite run."""

    __test__ = False

    suite_name: str
    agent_path: str
    model: str

    total: int = 0
    passed: int = 0
    failed: int = 0

    overall_score: float = Field(default=0.0, ge=0.0, le=1.0)
    avg_latency_ms: float = 0.0
    total_cost_usd: float = 0.0

    case_results: list[EvalCaseResult] = Field(default_factory=list)

    started_at: datetime = Field(default_factory=datetime.now)
    finished_at: datetime | None = None
    duration_ms: int = 0

    model_config = {"extra": "allow"}

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.passed / self.total

    @property
    def all_passed(self) -> bool:
        return self.failed == 0

    def get_failed(self) -> list[EvalCaseResult]:
        return [r for r in self.case_results if not r.passed]

    def print_summary(self) -> None:
        """Print a human-readable summary to stdout."""
        status = "PASSED" if self.all_passed else "FAILED"
        print(f"\n{'='*60}")
        print(f"  Eval Suite: {self.suite_name}  [{status}]")
        print(f"{'='*60}")
        print(f"  Agent      : {self.agent_path}")
        print(f"  Model      : {self.model}")
        print(f"  Cases      : {self.passed}/{self.total} passed ({self.pass_rate:.1%})")
        print(f"  Score      : {self.overall_score:.3f}")
        print(f"  Avg latency: {self.avg_latency_ms:.0f}ms")
        print(f"  Total cost : ${self.total_cost_usd:.6f}")
        print(f"  Duration   : {self.duration_ms}ms")
        print(f"{'='*60}")

        if self.get_failed():
            print("\n  Failed cases:")
            for r in self.get_failed():
                dims = ", ".join(d.name for d in r.dimensions if not d.passed)
                print(f"    ✗ {r.case_id}  (failed: {dims or 'unknown'})")
        print()

    def to_json(self, path: str | Path) -> None:
        """Save report as JSON."""
        Path(path).write_text(
            json.dumps(self.model_dump(mode="json"), indent=2, default=str)
        )

    def to_markdown(self, path: str | Path) -> None:
        """Save report as Markdown."""
        lines = [
            f"# Eval Report: {self.suite_name}",
            f"",
            f"| Field | Value |",
            f"|-------|-------|",
            f"| Agent | `{self.agent_path}` |",
            f"| Model | `{self.model}` |",
            f"| Pass rate | {self.pass_rate:.1%} ({self.passed}/{self.total}) |",
            f"| Overall score | {self.overall_score:.3f} |",
            f"| Avg latency | {self.avg_latency_ms:.0f}ms |",
            f"| Total cost | ${self.total_cost_usd:.6f} |",
            f"| Duration | {self.duration_ms}ms |",
            f"",
            f"## Case Results",
            f"",
            f"| Case | Passed | Score | Latency | Cost | Failed dimensions |",
            f"|------|--------|-------|---------|------|-------------------|",
        ]
        for r in self.case_results:
            failed_dims = ", ".join(d.name for d in r.dimensions if not d.passed) or "-"
            lines.append(
                f"| {r.case_id} | {'✓' if r.passed else '✗'} | "
                f"{r.score:.3f} | {r.latency_ms}ms | "
                f"${r.estimated_cost_usd:.6f} | {failed_dims} |"
            )
        Path(path).write_text("\n".join(lines))
