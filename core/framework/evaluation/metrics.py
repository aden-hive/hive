"""Metrics collection and aggregation for agent evaluation."""

from __future__ import annotations

import statistics
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EvaluationMetrics(BaseModel):
    """Metrics snapshot from a single agent execution."""

    run_id: str = ""
    agent_id: str = ""
    success: bool = False
    execution_quality: str = "clean"

    total_tokens: int = 0
    total_latency_ms: int = 0
    steps_executed: int = 0
    total_retries: int = 0

    estimated_cost_usd: float = 0.0

    criteria_met: int = 0
    criteria_total: int = 0
    constraint_violations: int = 0
    failure_count: int = 0
    failure_categories: dict[str, int] = Field(default_factory=dict)

    timestamp: datetime = Field(default_factory=datetime.now)

    model_config = {"extra": "allow"}

    @property
    def criteria_pass_rate(self) -> float:
        if self.criteria_total == 0:
            return 0.0
        return self.criteria_met / self.criteria_total

    @property
    def avg_latency_per_step_ms(self) -> float:
        if self.steps_executed == 0:
            return 0.0
        return self.total_latency_ms / self.steps_executed

    @property
    def tokens_per_step(self) -> float:
        if self.steps_executed == 0:
            return 0.0
        return self.total_tokens / self.steps_executed

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "success": self.success,
            "quality": self.execution_quality,
            "criteria": f"{self.criteria_met}/{self.criteria_total}",
            "tokens": self.total_tokens,
            "latency_ms": self.total_latency_ms,
            "cost_usd": f"${self.estimated_cost_usd:.4f}",
            "retries": self.total_retries,
            "failures": self.failure_count,
        }


class MetricsCollector:
    """Accumulates EvaluationMetrics across runs and computes aggregates.

    In-memory for now. Production should persist to TimescaleDB or similar.
    """

    def __init__(self, agent_id: str = "") -> None:
        self.agent_id = agent_id
        self._snapshots: list[EvaluationMetrics] = []

    def record(self, metrics: EvaluationMetrics) -> None:
        self._snapshots.append(metrics)

    @property
    def count(self) -> int:
        return len(self._snapshots)

    @property
    def snapshots(self) -> list[EvaluationMetrics]:
        return list(self._snapshots)

    def clear(self) -> None:
        self._snapshots.clear()

    def aggregate(self) -> dict[str, Any]:
        """Compute aggregate stats over all recorded snapshots."""
        if not self._snapshots:
            return {"total_runs": 0}

        n = len(self._snapshots)
        successes = [s for s in self._snapshots if s.success]
        latencies = [s.total_latency_ms for s in self._snapshots]
        tokens = [s.total_tokens for s in self._snapshots]
        costs = [s.estimated_cost_usd for s in self._snapshots]
        pass_rates = [s.criteria_pass_rate for s in self._snapshots]
        retries = [s.total_retries for s in self._snapshots]

        quality_dist: dict[str, int] = {}
        for s in self._snapshots:
            quality_dist[s.execution_quality] = quality_dist.get(s.execution_quality, 0) + 1

        cat_totals: dict[str, int] = {}
        for s in self._snapshots:
            for cat, count in s.failure_categories.items():
                cat_totals[cat] = cat_totals.get(cat, 0) + count

        return {
            "agent_id": self.agent_id,
            "total_runs": n,
            "success_rate": len(successes) / n,
            "avg_latency_ms": statistics.mean(latencies) if latencies else 0,
            "p95_latency_ms": (
                sorted(latencies)[int(n * 0.95)] if n >= 2 else (latencies[0] if latencies else 0)
            ),
            "avg_tokens": statistics.mean(tokens) if tokens else 0,
            "total_tokens": sum(tokens),
            "avg_cost_usd": statistics.mean(costs) if costs else 0.0,
            "total_cost_usd": sum(costs),
            "avg_criteria_pass_rate": statistics.mean(pass_rates) if pass_rates else 0.0,
            "avg_retries": statistics.mean(retries) if retries else 0,
            "failure_category_totals": cat_totals,
            "quality_distribution": quality_dist,
            "trend": self._compute_trend(),
        }

    def _compute_trend(self) -> str:
        """Compare first-half vs second-half success rate."""
        n = len(self._snapshots)
        if n < 4:
            return "insufficient_data"

        mid = n // 2
        first_rate = sum(1 for s in self._snapshots[:mid] if s.success) / mid
        second_rate = sum(1 for s in self._snapshots[mid:] if s.success) / (n - mid)

        diff = second_rate - first_rate
        if diff > 0.1:
            return "improving"
        if diff < -0.1:
            return "degrading"
        return "stable"

    def get_recent(self, n: int = 10) -> list[EvaluationMetrics]:
        return self._snapshots[-n:]
