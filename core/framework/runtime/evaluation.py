"""
Execution Evaluation System — the missing link for self-improvement.

Evaluates completed executions against goal criteria, stores historical
results, diagnoses failure patterns, and produces actionable improvement
recommendations that close the feedback loop.

Architecture:
  ExecutionStream → evaluate() → EvaluationResult
                                       ↓
                              EvaluationStore (persistent)
                                       ↓
                              diagnose() → ImprovementPlan
                                       ↓
                              (fed back into next execution via session_state)

References: Issue #3900 — RFC: Agent Evaluation System
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from framework.graph.executor import ExecutionResult
from framework.graph.goal import Goal, SuccessCriterion

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CriterionResult:
    """Evaluation of a single success criterion."""

    criterion_id: str
    description: str
    met: bool
    score: float  # 0.0–1.0
    evidence: str = ""
    metric_used: str = ""


@dataclass
class EvaluationResult:
    """Complete evaluation of one execution."""

    execution_id: str
    stream_id: str
    timestamp: datetime = field(default_factory=datetime.now)

    # Overall verdict
    success: bool = False
    overall_score: float = 0.0  # 0.0–1.0 weighted aggregate

    # Per-criterion breakdown
    criteria_results: list[CriterionResult] = field(default_factory=list)

    # Execution quality (from ExecutionResult)
    execution_quality: str = "clean"
    total_retries: int = 0
    total_tokens: int = 0
    total_latency_ms: int = 0
    steps_executed: int = 0

    # Constraint violations
    constraint_violations: list[str] = field(default_factory=list)

    # Efficiency metrics
    tokens_per_step: float = 0.0
    latency_per_step_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "stream_id": self.stream_id,
            "timestamp": self.timestamp.isoformat(),
            "success": self.success,
            "overall_score": self.overall_score,
            "criteria_results": [
                {
                    "criterion_id": c.criterion_id,
                    "description": c.description,
                    "met": c.met,
                    "score": c.score,
                    "evidence": c.evidence,
                    "metric_used": c.metric_used,
                }
                for c in self.criteria_results
            ],
            "execution_quality": self.execution_quality,
            "total_retries": self.total_retries,
            "total_tokens": self.total_tokens,
            "total_latency_ms": self.total_latency_ms,
            "steps_executed": self.steps_executed,
            "constraint_violations": self.constraint_violations,
            "tokens_per_step": self.tokens_per_step,
            "latency_per_step_ms": self.latency_per_step_ms,
        }


@dataclass
class ImprovementPlan:
    """Actionable diagnosis produced from evaluation history."""

    generated_at: datetime = field(default_factory=datetime.now)

    # Trend analysis
    recent_success_rate: float = 0.0
    trend: str = "stable"  # "improving", "degrading", "stable"

    # Problem areas
    failing_criteria: list[str] = field(default_factory=list)
    bottleneck_nodes: list[str] = field(default_factory=list)

    # Recommendations (injected into next execution's session_state)
    recommendations: list[str] = field(default_factory=list)

    # Efficiency observations
    avg_tokens_per_step: float = 0.0
    avg_latency_per_step_ms: float = 0.0

    def to_prompt_context(self) -> str:
        """Render as a context block for the agent's next execution."""
        if not self.recommendations:
            return ""

        lines = [
            "## Improvement Guidance (from prior executions)",
            f"Recent success rate: {self.recent_success_rate:.0%} | Trend: {self.trend}",
        ]

        if self.failing_criteria:
            lines.append(f"Weak criteria: {', '.join(self.failing_criteria)}")

        if self.bottleneck_nodes:
            lines.append(f"Bottleneck nodes: {', '.join(self.bottleneck_nodes)}")

        lines.append("")
        lines.append("Recommendations:")
        for i, rec in enumerate(self.recommendations, 1):
            lines.append(f"  {i}. {rec}")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at.isoformat(),
            "recent_success_rate": self.recent_success_rate,
            "trend": self.trend,
            "failing_criteria": self.failing_criteria,
            "bottleneck_nodes": self.bottleneck_nodes,
            "recommendations": self.recommendations,
            "avg_tokens_per_step": self.avg_tokens_per_step,
            "avg_latency_per_step_ms": self.avg_latency_per_step_ms,
        }


# ---------------------------------------------------------------------------
# Persistent store
# ---------------------------------------------------------------------------


class EvaluationStore:
    """Append-only JSON-lines store for evaluation history.

    Each line is one ``EvaluationResult.to_dict()`` dump.  The store is
    scoped per-stream so parallel streams don't pollute each other.
    """

    def __init__(self, base_path: Path | None = None) -> None:
        self._base = base_path or Path.home() / ".hive" / "evaluations"
        self._base.mkdir(parents=True, exist_ok=True)

    def _stream_path(self, stream_id: str) -> Path:
        # Sanitise stream_id for safe file names
        safe = stream_id.replace("/", "_").replace("\\", "_").replace("..", "_")
        return self._base / f"{safe}.jsonl"

    def record(self, result: EvaluationResult) -> None:
        """Append an evaluation result."""
        path = self._stream_path(result.stream_id)
        with open(path, "a") as f:
            f.write(json.dumps(result.to_dict()) + "\n")

    def load_history(self, stream_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Load the most recent *limit* evaluations for a stream."""
        path = self._stream_path(stream_id)
        if not path.exists():
            return []
        lines = path.read_text().strip().splitlines()
        recent = lines[-limit:]
        results: list[dict[str, Any]] = []
        for line in recent:
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return results


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


class ExecutionEvaluator:
    """Evaluates a completed execution against goal criteria.

    This is the *execute → evaluate* leg of the self-improvement loop.
    """

    def __init__(self, store: EvaluationStore | None = None) -> None:
        self._store = store or EvaluationStore()

    # ----- public API -----

    def evaluate(
        self,
        result: ExecutionResult,
        goal: Goal,
        stream_id: str,
        execution_id: str,
    ) -> EvaluationResult:
        """Evaluate a single execution result against the goal."""
        criteria_results = [
            self._evaluate_criterion(c, result) for c in goal.success_criteria
        ]

        # Weighted aggregate
        total_weight = sum(c.weight for c in goal.success_criteria) or 1.0
        weighted_score = sum(
            cr.score * sc.weight
            for cr, sc in zip(criteria_results, goal.success_criteria)
        )
        overall_score = weighted_score / total_weight

        # Efficiency
        steps = max(result.steps_executed, 1)
        tokens_per_step = result.total_tokens / steps
        latency_per_step = result.total_latency_ms / steps

        # Constraint violations
        violations: list[str] = []
        for c in goal.constraints:
            if c.constraint_type == "hard":
                if c.category == "cost" and result.total_tokens > 100_000:
                    violations.append(f"{c.id}: token budget exceeded ({result.total_tokens})")
                if c.category == "time" and result.total_latency_ms > 300_000:
                    violations.append(f"{c.id}: latency budget exceeded ({result.total_latency_ms}ms)")

        evaluation = EvaluationResult(
            execution_id=execution_id,
            stream_id=stream_id,
            success=result.success and overall_score >= 0.7,
            overall_score=overall_score,
            criteria_results=criteria_results,
            execution_quality=result.execution_quality,
            total_retries=result.total_retries,
            total_tokens=result.total_tokens,
            total_latency_ms=result.total_latency_ms,
            steps_executed=result.steps_executed,
            constraint_violations=violations,
            tokens_per_step=tokens_per_step,
            latency_per_step_ms=latency_per_step,
        )

        # Persist
        self._store.record(evaluation)
        logger.info(
            "Evaluation for %s: score=%.2f success=%s quality=%s",
            execution_id,
            overall_score,
            evaluation.success,
            result.execution_quality,
        )

        return evaluation

    def diagnose(self, stream_id: str, window: int = 10) -> ImprovementPlan:
        """Analyse recent evaluation history and produce an improvement plan.

        This is the *evaluate → diagnose → recommend* leg of the loop.
        """
        history = self._store.load_history(stream_id, limit=window)
        if not history:
            return ImprovementPlan()

        # --- trend analysis ---
        successes = [h["success"] for h in history]
        recent_rate = sum(successes) / len(successes)

        # Compare first half vs second half
        mid = len(successes) // 2 or 1
        first_half_rate = sum(successes[:mid]) / max(mid, 1)
        second_half_rate = sum(successes[mid:]) / max(len(successes) - mid, 1)
        if second_half_rate - first_half_rate > 0.15:
            trend = "improving"
        elif first_half_rate - second_half_rate > 0.15:
            trend = "degrading"
        else:
            trend = "stable"

        # --- failing criteria ---
        criterion_scores: dict[str, list[float]] = {}
        for h in history:
            for cr in h.get("criteria_results", []):
                cid = cr["criterion_id"]
                criterion_scores.setdefault(cid, []).append(cr["score"])

        failing_criteria = [
            cid
            for cid, scores in criterion_scores.items()
            if (sum(scores) / len(scores)) < 0.6
        ]

        # --- bottleneck nodes (high retry nodes) ---
        retry_details_all: dict[str, int] = {}
        for h in history:
            for nid, count in (h.get("retry_details") or {}).items():
                retry_details_all[nid] = retry_details_all.get(nid, 0) + count
        bottleneck_nodes = sorted(retry_details_all, key=retry_details_all.get, reverse=True)[:3]  # type: ignore[arg-type]

        # --- efficiency ---
        avg_tps = sum(h.get("tokens_per_step", 0) for h in history) / len(history)
        avg_lps = sum(h.get("latency_per_step_ms", 0) for h in history) / len(history)

        # --- generate recommendations ---
        recs: list[str] = []

        if trend == "degrading":
            recs.append(
                "Performance is degrading across recent runs. "
                "Review recent changes to prompts or tool configurations."
            )

        for cid in failing_criteria:
            scores = criterion_scores[cid]
            avg = sum(scores) / len(scores)
            recs.append(
                f"Criterion '{cid}' has avg score {avg:.0%} — "
                "consider adding more specific guidance in the node's system prompt."
            )

        for nid in bottleneck_nodes:
            recs.append(
                f"Node '{nid}' has high retry rate — "
                "check its output validation and success criteria."
            )

        if avg_tps > 5000:
            recs.append(
                f"Token usage is high ({avg_tps:.0f}/step). "
                "Consider trimming context or splitting large nodes."
            )

        if not recs:
            recs.append("No issues detected — continue current approach.")

        return ImprovementPlan(
            recent_success_rate=recent_rate,
            trend=trend,
            failing_criteria=failing_criteria,
            bottleneck_nodes=bottleneck_nodes,
            recommendations=recs,
            avg_tokens_per_step=avg_tps,
            avg_latency_per_step_ms=avg_lps,
        )

    # ----- criterion evaluation -----

    def _evaluate_criterion(
        self, criterion: SuccessCriterion, result: ExecutionResult
    ) -> CriterionResult:
        """Evaluate a single criterion against execution output."""
        metric = criterion.metric
        target = criterion.target
        output = result.output

        if metric == "output_contains":
            return self._eval_output_contains(criterion, output, target)
        elif metric == "output_equals":
            return self._eval_output_equals(criterion, output, target)
        elif metric == "success_rate":
            # Binary: did the execution succeed?
            return CriterionResult(
                criterion_id=criterion.id,
                description=criterion.description,
                met=result.success,
                score=1.0 if result.success else 0.0,
                evidence=f"execution success={result.success}",
                metric_used="success_rate",
            )
        else:
            # Fallback: use execution success as proxy
            return CriterionResult(
                criterion_id=criterion.id,
                description=criterion.description,
                met=result.success,
                score=1.0 if result.success else 0.0,
                evidence=f"fallback — metric '{metric}' not yet implemented",
                metric_used=metric,
            )

    @staticmethod
    def _eval_output_contains(
        criterion: SuccessCriterion, output: dict, target: Any
    ) -> CriterionResult:
        target_str = str(target)
        output_str = json.dumps(output, default=str)
        found = target_str.lower() in output_str.lower()
        return CriterionResult(
            criterion_id=criterion.id,
            description=criterion.description,
            met=found,
            score=1.0 if found else 0.0,
            evidence=f"looked for '{target_str}' in output: {'found' if found else 'not found'}",
            metric_used="output_contains",
        )

    @staticmethod
    def _eval_output_equals(
        criterion: SuccessCriterion, output: dict, target: Any
    ) -> CriterionResult:
        target_key = str(target)
        # Check if the target key exists and its value matches expected
        actual = output.get(target_key)
        if actual is not None:
            return CriterionResult(
                criterion_id=criterion.id,
                description=criterion.description,
                met=True,
                score=1.0,
                evidence=f"key '{target_key}' present in output",
                metric_used="output_equals",
            )
        return CriterionResult(
            criterion_id=criterion.id,
            description=criterion.description,
            met=False,
            score=0.0,
            evidence=f"key '{target_key}' missing from output",
            metric_used="output_equals",
        )
