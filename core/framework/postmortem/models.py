"""Data model for post-mortem analysis of a runtime log run.

A post-mortem turns the three levels of runtime logs (see
``framework.tracker.runtime_log_schemas``) into a small, ranked set of
``Finding`` objects plus a ``RunVitals`` roll-up. Nothing here touches the
live runtime — the analysis is a pure function of what is already on disk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    """How much a finding should worry the operator.

    Ordered by ``RANK`` below so reports can sort worst-first.
    """

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


# Sort weight for severities. Higher = more urgent.
RANK: dict[Severity, int] = {
    Severity.CRITICAL: 4,
    Severity.HIGH: 3,
    Severity.MEDIUM: 2,
    Severity.LOW: 1,
    Severity.INFO: 0,
}


@dataclass
class Finding:
    """One diagnosed problem in a run.

    ``code`` is a stable machine-readable slug (e.g. ``tool_thrash``) so that
    downstream tooling and tests can assert on findings without matching prose.
    ``evidence`` holds short, already-formatted lines shown verbatim under the
    finding; keep raw payloads out of it, reports are meant to stay readable.
    """

    code: str
    title: str
    severity: Severity
    detail: str
    suggestion: str = ""
    node_id: str = ""
    evidence: list[str] = field(default_factory=list)
    # Free-form numbers backing the finding, surfaced only in JSON output.
    metrics: dict[str, Any] = field(default_factory=dict)

    def sort_key(self) -> tuple[int, str]:
        return (-RANK[self.severity], self.code)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "severity": self.severity.value,
            "detail": self.detail,
            "suggestion": self.suggestion,
            "node_id": self.node_id,
            "evidence": list(self.evidence),
            "metrics": dict(self.metrics),
        }


@dataclass
class RunVitals:
    """Headline numbers for a run, derived from all three log levels."""

    run_id: str
    agent_id: str = ""
    goal_id: str = ""
    status: str = ""
    started_at: str = ""
    duration_ms: int = 0
    nodes_executed: int = 0
    steps: int = 0
    tool_calls: int = 0
    tool_errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    # Input tokens that are conversation prefix re-sent on later steps.
    # Approximated as (sum of per-step input tokens) - (largest single step),
    # i.e. everything beyond the one unavoidable full-context send.
    resend_overhead_tokens: int = 0
    model: str = ""
    cost_usd: float | None = None
    cost_source: str = ""

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def tool_error_rate(self) -> float:
        return self.tool_errors / self.tool_calls if self.tool_calls else 0.0

    def to_dict(self) -> dict[str, Any]:
        data = {
            "run_id": self.run_id,
            "agent_id": self.agent_id,
            "goal_id": self.goal_id,
            "status": self.status,
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
            "nodes_executed": self.nodes_executed,
            "steps": self.steps,
            "tool_calls": self.tool_calls,
            "tool_errors": self.tool_errors,
            "tool_error_rate": round(self.tool_error_rate, 4),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "resend_overhead_tokens": self.resend_overhead_tokens,
            "model": self.model,
            "cost_usd": self.cost_usd,
            "cost_source": self.cost_source,
        }
        return data


@dataclass
class Report:
    """A complete post-mortem: vitals plus ranked findings."""

    vitals: RunVitals
    findings: list[Finding] = field(default_factory=list)
    # Notes about missing/partial inputs (e.g. no summary.json for a crashed run).
    warnings: list[str] = field(default_factory=list)

    @property
    def worst_severity(self) -> Severity | None:
        if not self.findings:
            return None
        return max((f.severity for f in self.findings), key=lambda s: RANK[s])

    def sorted_findings(self) -> list[Finding]:
        return sorted(self.findings, key=lambda f: f.sort_key())

    def to_dict(self) -> dict[str, Any]:
        return {
            "vitals": self.vitals.to_dict(),
            "findings": [f.to_dict() for f in self.sorted_findings()],
            "warnings": list(self.warnings),
            "worst_severity": self.worst_severity.value if self.worst_severity else None,
        }


@dataclass
class Thresholds:
    """Tunable detector thresholds.

    Defaults are deliberately conservative: a clean run should produce an
    empty findings list, so anything reported is worth a human's attention.
    """

    # tool_thrash: identical (tool, input) repeats inside one node
    thrash_min_repeats: int = 3
    thrash_high_repeats: int = 6
    # failing_tools
    tool_fail_min_errors: int = 2
    tool_fail_min_rate: float = 0.25
    tool_fail_high_rate: float = 0.5
    # retry_storm
    retry_warn: int = 3
    retry_high: int = 6
    escalate_warn: int = 2
    # context_growth
    growth_min_steps: int = 4
    growth_factor: float = 3.0
    growth_min_tokens: int = 20_000
    # resend_overhead
    resend_min_total_tokens: int = 50_000
    resend_ratio: float = 0.6
    # slow_tools (seconds)
    slow_tool_s: float = 30.0
    slow_tool_high_s: float = 60.0
    # oversized tool results (characters of returned text)
    big_result_chars: int = 40_000
    # repeated identical assistant turns inside one node
    repeat_min: int = 3
    # how many evidence lines any single finding may carry
    max_evidence: int = 5
