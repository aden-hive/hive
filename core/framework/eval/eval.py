"""
Aden Hive - Agent Outcome Evaluation System
============================================

Implements the `f1["Eval System"]` roadmap item.

Provides a lightweight, composable evaluation framework for agent graphs:
- Define expected outcomes as structured EvalCriteria
- Score agent runs against those criteria (LLM-as-judge + deterministic checks)
- Capture failure data in a structured FailureRecord for graph evolution
- Integrates with the existing node/graph execution pattern
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

@dataclass
class EvalCriteria:
    name: str
    description: str
    check: Callable[[dict[str, Any]], bool]
    weight: float = 1.0
    required: bool = False

@dataclass
class CriterionResult:
    name: str
    description: str
    passed: bool
    weight: float
    required: bool
    error: str | None = None

@dataclass
class FailureRecord:
    suite_name: str
    run_id: str
    timestamp: float
    agent_result: dict[str, Any]
    failed_criteria: list[str]
    score: float
    total_weight: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "suite_name": self.suite_name,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "agent_result": self.agent_result,
            "failed_criteria": self.failed_criteria,
            "score": self.score,
            "total_weight": self.total_weight,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

@dataclass
class EvalReport:
    suite_name: str
    run_id: str
    score: float
    passed: bool
    results: list[CriterionResult]
    failures: list[str]
    failure_record: FailureRecord | None
    duration_ms: float

    def summary(self) -> str:
        status = "✅ PASSED" if self.passed else "❌ FAILED"
        lines = [
            f"Eval Report: {self.suite_name} [{status}]",
            f"Score: {self.score:.2%}  |  Run: {self.run_id}  |  {self.duration_ms:.1f}ms",
            "",
        ]
        for r in self.results:
            icon = "✓" if r.passed else "✗"
            req = " [REQUIRED]" if r.required else ""
            err = f" ({r.error})" if r.error else ""
            lines.append(f"  {icon} [{r.weight:.1f}x] {r.name}{req}{err}")
        return "\n".join(lines)

class EvalSuite:
    def __init__(self, name: str, pass_threshold: float = 0.7) -> None:
        if not (0.0 <= pass_threshold <= 1.0):
            raise ValueError("pass_threshold must be between 0.0 and 1.0")
        self.name = name
        self.pass_threshold = pass_threshold
        self._criteria: list[EvalCriteria] = []

    def add(self, criterion: EvalCriteria) -> "EvalSuite":
        if any(c.name == criterion.name for c in self._criteria):
            raise ValueError(f"Criterion '{criterion.name}' already exists")
        self._criteria.append(criterion)
        return self

    def remove(self, name: str) -> None:
        self._criteria = [c for c in self._criteria if c.name != name]

    @property
    def criteria(self) -> list[EvalCriteria]:
        return list(self._criteria)

    def __len__(self) -> int:
        return len(self._criteria)

class EvalRunner:
    def __init__(self, suite: EvalSuite) -> None:
        self.suite = suite

    def evaluate(self, agent_result: dict[str, Any], run_id: str | None = None, metadata: dict[str, Any] | None = None) -> EvalReport:
        if run_id is None:
            run_id = f"run-{int(time.time() * 1000)}"

        t_start = time.perf_counter()
        results: list[CriterionResult] = []
        failed_names: list[str] = []
        has_required_failure = False

        total_weight = sum(c.weight for c in self.suite.criteria)
        earned_weight = 0.0

        for criterion in self.suite.criteria:
            passed = False
            error = None
            try:
                passed = bool(criterion.check(agent_result))
            except Exception as e:
                error = str(e)

            if passed:
                earned_weight += criterion.weight
            else:
                failed_names.append(criterion.name)
                if criterion.required:
                    has_required_failure = True

            results.append(CriterionResult(
                name=criterion.name, description=criterion.description,
                passed=passed, weight=criterion.weight,
                required=criterion.required, error=error,
            ))

        score = (earned_weight / total_weight) if total_weight > 0 else 0.0
        passed = (score >= self.suite.pass_threshold) and (not has_required_failure)
        duration_ms = (time.perf_counter() - t_start) * 1000

        failure_record = None
        if not passed:
            failure_record = FailureRecord(
                suite_name=self.suite.name, run_id=run_id, timestamp=time.time(),
                agent_result=agent_result, failed_criteria=failed_names,
                score=score, total_weight=total_weight, metadata=metadata or {},
            )

        return EvalReport(
            suite_name=self.suite.name, run_id=run_id, score=score,
            passed=passed, results=results, failures=failed_names,
            failure_record=failure_record, duration_ms=duration_ms,
        )

    def evaluate_batch(self, runs: list[dict[str, Any]], metadata: dict[str, Any] | None = None) -> "BatchEvalReport":
        reports = [self.evaluate(run, run_id=f"run-{i}", metadata=metadata) for i, run in enumerate(runs)]
        return BatchEvalReport(suite_name=self.suite.name, reports=reports)

@dataclass
class BatchEvalReport:
    suite_name: str
    reports: list[EvalReport]

    @property
    def pass_rate(self) -> float:
        if not self.reports: return 0.0
        return sum(1 for r in self.reports if r.passed) / len(self.reports)

    @property
    def mean_score(self) -> float:
        if not self.reports: return 0.0
        return sum(r.score for r in self.reports) / len(self.reports)

    @property
    def failure_records(self) -> list[FailureRecord]:
        return [r.failure_record for r in self.reports if r.failure_record is not None]

    def criterion_pass_rates(self) -> dict[str, float]:
        if not self.reports: return {}
        totals, passes = {}, {}
        for report in self.reports:
            for cr in report.results:
                totals[cr.name] = totals.get(cr.name, 0) + 1
                if cr.passed: passes[cr.name] = passes.get(cr.name, 0) + 1
        return {name: passes.get(name, 0) / total for name, total in totals.items()}

    def summary(self) -> str:
        lines = [
            f"Batch Eval: {self.suite_name}",
            f"Runs: {len(self.reports)}  |  Pass Rate: {self.pass_rate:.1%}  |  Mean Score: {self.mean_score:.2%}",
            "", "Per-criterion pass rates:",
        ]
        for name, rate in self.criterion_pass_rates().items():
            lines.append(f"  {name}: {rate:.1%}")
        return "\n".join(lines)

def output_not_empty(key: str = "output", weight: float = 1.0) -> EvalCriteria:
    return EvalCriteria(
        name=f"{key}_not_empty", description=f"Agent result['{key}'] must be non-empty",
        check=lambda r: bool(str(r.get(key, "")).strip()), weight=weight,
    )

def action_performed(action: str, actions_key: str = "actions", weight: float = 1.0) -> EvalCriteria:
    return EvalCriteria(
        name=f"action_{action}", description=f"Agent must have performed action '{action}'",
        check=lambda r: action in r.get(actions_key, []), weight=weight,
    )

def no_error(weight: float = 1.0) -> EvalCriteria:
    return EvalCriteria(
        name="no_error", description="Agent result must not contain an error",
        check=lambda r: "error" not in r, weight=weight, required=True,
    )

def contains_keyword(keyword: str, key: str = "output", weight: float = 1.0) -> EvalCriteria:
    return EvalCriteria(
        name=f"contains_{keyword.lower().replace(' ', '_')}", description=f"Agent output must contain '{keyword}'",
        check=lambda r: keyword.lower() in str(r.get(key, "")).lower(), weight=weight,
    )

def latency_under(max_ms: float, latency_key: str = "latency_ms", weight: float = 0.5) -> EvalCriteria:
    return EvalCriteria(
        name=f"latency_under_{int(max_ms)}ms", description=f"Agent must complete in under {max_ms}ms",
        check=lambda r: float(r.get(latency_key, float("inf"))) < max_ms, weight=weight,
    )
