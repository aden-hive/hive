"""
Outcome Aggregator - Aggregates outcomes across streams for goal evaluation.

The goal-driven nature of Hive means we need to track whether
concurrent executions collectively achieve the goal.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from framework.schemas.decision import Decision, Outcome
from framework.schemas.failure_report import (
    FailureReport,
    UnmetCriterion,
    ViolatedConstraint,
)

if TYPE_CHECKING:
    from framework.graph.goal import Goal, SuccessCriterion
    from framework.llm.provider import LLMProvider
    from framework.runtime.event_bus import EventBus
    from framework.runtime.notifications import DeveloperNotifier

logger = logging.getLogger(__name__)


@dataclass
class CriterionStatus:
    """Status of a success criterion."""

    criterion_id: str
    description: str
    met: bool
    evidence: list[str] = field(default_factory=list)
    progress: float = 0.0  # 0.0 to 1.0
    last_updated: datetime = field(default_factory=datetime.now)


@dataclass
class ConstraintCheck:
    """Result of a constraint check."""

    constraint_id: str
    description: str
    violated: bool
    violation_details: str | None = None
    stream_id: str | None = None
    execution_id: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class DecisionRecord:
    """Record of a decision for aggregation."""

    stream_id: str
    execution_id: str
    decision: Decision
    outcome: Outcome | None = None
    timestamp: datetime = field(default_factory=datetime.now)


class OutcomeAggregator:
    """
    Aggregates outcomes across all execution streams for goal evaluation.

    Responsibilities:
    - Track all decisions across streams
    - Evaluate success criteria progress
    - Detect constraint violations
    - Provide unified goal progress metrics

    Example:
        aggregator = OutcomeAggregator(goal, event_bus)

        # Decisions are automatically recorded by StreamRuntime
        aggregator.record_decision(stream_id, execution_id, decision)
        aggregator.record_outcome(stream_id, execution_id, decision_id, outcome)

        # Evaluate goal progress
        progress = await aggregator.evaluate_goal_progress()
        print(f"Goal progress: {progress['overall_progress']:.1%}")
    """

    def __init__(
        self,
        goal: "Goal",
        event_bus: "EventBus | None" = None,
        llm_provider: "LLMProvider | None" = None,
        storage_path: "str | Path | None" = None,
        notifier: "DeveloperNotifier | None" = None,
    ):
        """
        Initialize outcome aggregator.

        Args:
            goal: The goal to evaluate progress against
            event_bus: Optional event bus for publishing progress events
            llm_provider: Optional LLM provider for llm_judge criteria
            storage_path: Optional path for persisting failure reports
        """
        self.goal = goal
        self._event_bus = event_bus
        self._llm_provider = llm_provider
        self._storage_path = Path(storage_path) if storage_path else None
        self._notifier = notifier

        # Decision tracking
        self._decisions: list[DecisionRecord] = []
        self._decisions_by_id: dict[str, DecisionRecord] = {}
        self._lock = asyncio.Lock()

        # Criterion tracking
        self._criterion_status: dict[str, CriterionStatus] = {}
        self._initialize_criteria()

        # Constraint tracking
        self._constraint_violations: list[ConstraintCheck] = []

        # Metrics
        self._total_decisions = 0
        self._successful_outcomes = 0
        self._failed_outcomes = 0

        # Last failure report (populated when goal fails)
        self._last_failure_report: FailureReport | None = None

    def _initialize_criteria(self) -> None:
        """Initialize criterion status from goal."""
        for criterion in self.goal.success_criteria:
            self._criterion_status[criterion.id] = CriterionStatus(
                criterion_id=criterion.id,
                description=criterion.description,
                met=False,
                progress=0.0,
            )

    # === DECISION RECORDING ===

    def record_decision(
        self,
        stream_id: str,
        execution_id: str,
        decision: Decision,
    ) -> None:
        """
        Record a decision from any stream.

        Args:
            stream_id: Which stream made the decision
            execution_id: Which execution
            decision: The decision made
        """
        record = DecisionRecord(
            stream_id=stream_id,
            execution_id=execution_id,
            decision=decision,
        )

        # Create unique key for lookup
        key = f"{stream_id}:{execution_id}:{decision.id}"
        self._decisions.append(record)
        self._decisions_by_id[key] = record
        self._total_decisions += 1

        logger.debug(f"Recorded decision {decision.id} from {stream_id}/{execution_id}")

    def record_outcome(
        self,
        stream_id: str,
        execution_id: str,
        decision_id: str,
        outcome: Outcome,
    ) -> None:
        """
        Record the outcome of a decision.

        Args:
            stream_id: Which stream
            execution_id: Which execution
            decision_id: Which decision
            outcome: The outcome
        """
        key = f"{stream_id}:{execution_id}:{decision_id}"
        record = self._decisions_by_id.get(key)

        if record:
            record.outcome = outcome

            if outcome.success:
                self._successful_outcomes += 1
            else:
                self._failed_outcomes += 1

            logger.debug(f"Recorded outcome for {decision_id}: success={outcome.success}")

    def record_constraint_violation(
        self,
        constraint_id: str,
        description: str,
        violation_details: str,
        stream_id: str | None = None,
        execution_id: str | None = None,
    ) -> None:
        """
        Record a constraint violation.

        Args:
            constraint_id: Which constraint was violated
            description: Constraint description
            violation_details: What happened
            stream_id: Which stream
            execution_id: Which execution
        """
        check = ConstraintCheck(
            constraint_id=constraint_id,
            description=description,
            violated=True,
            violation_details=violation_details,
            stream_id=stream_id,
            execution_id=execution_id,
        )

        self._constraint_violations.append(check)
        logger.warning(f"Constraint violation: {constraint_id} - {violation_details}")

        # Publish event if event bus available
        if self._event_bus and stream_id:
            asyncio.create_task(
                self._event_bus.emit_constraint_violation(
                    stream_id=stream_id,
                    execution_id=execution_id or "",
                    constraint_id=constraint_id,
                    description=violation_details,
                )
            )

    # === CRITERION EVALUATION ===

    async def evaluate_criterion(
        self,
        criterion: "SuccessCriterion",
        execution_output: Any,
    ) -> bool:
        """Evaluate a single criterion against an execution output.

        Dispatches based on criterion.metric:
        - 'output_contains': checks target substring in str(output)
        - 'output_equals': checks str(output) == str(target)
        - 'llm_judge': uses LLM to evaluate (requires llm_provider)
        - 'custom': evaluates target as a safe expression with output in scope

        Args:
            criterion: The success criterion to evaluate.
            execution_output: The output from an execution run.

        Returns:
            True if the criterion is met.
        """
        metric = criterion.metric
        target = criterion.target

        try:
            if metric == "output_contains":
                return self._eval_output_contains(target, execution_output)
            elif metric == "output_equals":
                return self._eval_output_equals(target, execution_output)
            elif metric == "llm_judge":
                return await self._eval_llm_judge(criterion, execution_output)
            elif metric == "custom":
                return self._eval_custom(target, execution_output)
            else:
                # Unknown metric — fall back to success_rate heuristic
                logger.debug(
                    f"Unknown metric '{metric}' for criterion {criterion.id}, "
                    "skipping output-based evaluation"
                )
                return False
        except Exception as e:
            logger.warning(f"Error evaluating criterion {criterion.id}: {e}")
            return False

    async def evaluate_output(self, execution_output: Any) -> bool:
        """Evaluate all goal criteria against an execution output.

        Sets criterion.met on each SuccessCriterion and returns
        goal.is_success(). When the goal is not achieved, automatically
        generates a FailureReport and persists it to disk (if storage_path
        is configured).

        Args:
            execution_output: The output from an execution run.

        Returns:
            True if the goal is achieved (via goal.is_success()).
        """
        for criterion in self.goal.success_criteria:
            met = await self.evaluate_criterion(criterion, execution_output)
            criterion.met = met

            status = self._criterion_status.get(criterion.id)
            if status:
                status.met = met
                status.progress = 1.0 if met else status.progress
                if met:
                    status.evidence.append(
                        f"criterion met via {criterion.metric} evaluation"
                    )

        success = self.goal.is_success()
        if not success:
            report = self.generate_failure_report()
            # Append to the goal's failure history with a monotonic version
            # so callers (e.g. evolution) can iterate the full history.
            report.version = len(self.goal.failure_history) + 1
            self.goal.failure_history.append(report)
            self._last_failure_report = report
            self.save_failure_report(report)

            # Phase 4: developer notification on failure (best-effort)
            if self._notifier is not None:
                try:
                    self._notifier.notify_failure(report)
                except Exception as e:
                    logger.warning(f"Notifier.notify_failure failed: {e}")

        return success

    # === FAILURE REPORTING ===

    @property
    def last_failure_report(self) -> FailureReport | None:
        """The most recent failure report, or None if the goal succeeded."""
        return self._last_failure_report

    def generate_failure_report(self) -> FailureReport:
        """Build a FailureReport from current aggregator state.

        Synthesizes unmet criteria, violated constraints, relevant node IDs
        from the execution trace, and a human-readable summary.
        """
        # Collect unmet criteria
        unmet = [
            UnmetCriterion(
                criterion_id=c.id,
                description=c.description,
                metric=c.metric,
                target=c.target,
                weight=c.weight,
            )
            for c in self.goal.success_criteria
            if not c.met
        ]

        # Collect violated constraints
        violated = [
            ViolatedConstraint(
                constraint_id=v.constraint_id,
                description=v.description,
                constraint_type=self._constraint_type_for(v.constraint_id),
                violation_details=v.violation_details or "",
                stream_id=v.stream_id,
                execution_id=v.execution_id,
            )
            for v in self._constraint_violations
            if v.violated
        ]

        # Collect node IDs from decisions whose outcomes failed
        node_ids: list[str] = []
        seen: set[str] = set()
        for rec in self._decisions:
            nid = rec.decision.node_id
            if nid in seen:
                continue
            # Include nodes with failed outcomes, or nodes related to
            # unmet criteria (by keyword overlap)
            if rec.outcome and not rec.outcome.success:
                node_ids.append(nid)
                seen.add(nid)
            elif any(
                self._is_related_to_criterion(rec.decision, c)
                for c in self.goal.success_criteria
                if not c.met
            ):
                node_ids.append(nid)
                seen.add(nid)

        # Derive edge IDs from consecutive decisions in the trace.
        # An edge "src->dst" is included when either endpoint is a node
        # already flagged as failure-relevant, so evolution can target the
        # transitions that led into/out of failing nodes.
        edge_ids: list[str] = []
        edge_seen: set[str] = set()
        flagged = set(node_ids)
        for prev, curr in zip(self._decisions, self._decisions[1:]):
            src = prev.decision.node_id
            dst = curr.decision.node_id
            if src == dst:
                continue
            if src not in flagged and dst not in flagged:
                continue
            edge_id = f"{src}->{dst}"
            if edge_id in edge_seen:
                continue
            edge_ids.append(edge_id)
            edge_seen.add(edge_id)

        summary = self._build_failure_summary(unmet, violated, node_ids)

        # Tag the report with an ErrorCategory derived from the summary +
        # any constraint violation details. Best-effort: failures here are
        # non-fatal because the categorizer is only an evolution hint.
        error_category: str | None = None
        try:
            from framework.testing.categorizer import ErrorCategorizer

            cat_text_parts = [summary] + [v.violation_details for v in violated]
            cat_text = " ".join(p for p in cat_text_parts if p)
            error_category = str(ErrorCategorizer().categorize_text(cat_text))
        except Exception as e:
            logger.debug(f"Skipping error categorization: {e}")

        return FailureReport(
            goal_id=self.goal.id,
            goal_name=self.goal.name,
            unmet_criteria=unmet,
            violated_constraints=violated,
            node_ids=node_ids,
            edge_ids=edge_ids,
            error_category=error_category,
            summary=summary,
            total_decisions=self._total_decisions,
            successful_outcomes=self._successful_outcomes,
            failed_outcomes=self._failed_outcomes,
        )

    def save_failure_report(self, report: FailureReport) -> Path | None:
        """Persist a failure report to disk.

        Writes to ``{storage_path}/failure_reports/{goal_id}_{timestamp}.json``.
        Returns the path written, or None if no storage_path is configured.
        """
        if self._storage_path is None:
            return None

        reports_dir = self._storage_path / "failure_reports"
        reports_dir.mkdir(parents=True, exist_ok=True)

        timestamp = report.timestamp.strftime("%Y%m%d_%H%M%S")
        filename = f"{report.goal_id}_{timestamp}.json"
        report_path = reports_dir / filename

        try:
            from framework.utils.io import atomic_write

            with atomic_write(report_path) as f:
                f.write(report.model_dump_json(indent=2))
            logger.info(f"Saved failure report to {report_path}")
            return report_path
        except Exception as e:
            logger.error(f"Failed to save failure report: {e}")
            return None

    def _constraint_type_for(self, constraint_id: str) -> str:
        """Look up constraint_type from the goal's constraint list."""
        for c in self.goal.constraints:
            if c.id == constraint_id:
                return c.constraint_type
        return "unknown"

    @staticmethod
    def _build_failure_summary(
        unmet: list[UnmetCriterion],
        violated: list[ViolatedConstraint],
        node_ids: list[str],
    ) -> str:
        parts: list[str] = []

        if unmet:
            criteria_desc = "; ".join(c.description for c in unmet)
            parts.append(f"{len(unmet)} unmet criteria: {criteria_desc}")

        if violated:
            hard = [v for v in violated if v.constraint_type == "hard"]
            soft = [v for v in violated if v.constraint_type != "hard"]
            if hard:
                parts.append(
                    f"{len(hard)} hard constraint violation(s): "
                    + "; ".join(v.violation_details for v in hard)
                )
            if soft:
                parts.append(f"{len(soft)} soft constraint violation(s)")

        if node_ids:
            parts.append(f"Relevant nodes: {', '.join(node_ids)}")

        if not parts:
            return "Goal not achieved (no specific failure details available)."
        return "Goal not achieved. " + ". ".join(parts) + "."

    # --- metric dispatch helpers ---

    @staticmethod
    def _eval_output_contains(target: Any, output: Any) -> bool:
        output_str = str(output)
        target_str = str(target)
        return target_str in output_str

    @staticmethod
    def _eval_output_equals(target: Any, output: Any) -> bool:
        # Try exact match first, then string comparison
        if output == target:
            return True
        return str(output).strip() == str(target).strip()

    async def _eval_llm_judge(
        self,
        criterion: "SuccessCriterion",
        output: Any,
    ) -> bool:
        if self._llm_provider is None:
            logger.warning(
                f"llm_judge requested for criterion {criterion.id} "
                "but no LLM provider configured — skipping"
            )
            return False

        from framework.graph.judge import judge_criterion

        return await judge_criterion(self._llm_provider, criterion, output)

    @staticmethod
    def _eval_custom(target: Any, output: Any) -> bool:
        """Evaluate a custom expression using safe_eval.

        The target is treated as a Python expression string.
        The variable 'output' is available in the expression scope.
        """
        from framework.graph.safe_eval import safe_eval

        expr = str(target)
        result = safe_eval(expr, {"output": output})
        return bool(result)

    # === GOAL EVALUATION ===

    async def evaluate_goal_progress(self) -> dict[str, Any]:
        """
        Evaluate progress toward goal across all streams.

        Returns:
            {
                "overall_progress": 0.0-1.0,
                "criteria_status": {criterion_id: {...}},
                "constraint_violations": [...],
                "metrics": {...},
                "recommendation": "continue" | "adjust" | "complete"
            }
        """
        async with self._lock:
            result = {
                "overall_progress": 0.0,
                "criteria_status": {},
                "constraint_violations": [],
                "metrics": {},
                "recommendation": "continue",
            }

            # Evaluate each success criterion
            total_weight = 0.0
            met_weight = 0.0

            for criterion in self.goal.success_criteria:
                status = await self._evaluate_criterion(criterion)
                self._criterion_status[criterion.id] = status
                result["criteria_status"][criterion.id] = {
                    "description": status.description,
                    "met": status.met,
                    "progress": status.progress,
                    "evidence": status.evidence,
                }

                total_weight += criterion.weight
                if status.met:
                    met_weight += criterion.weight
                else:
                    # Partial credit based on progress
                    met_weight += criterion.weight * status.progress

            # Calculate overall progress
            if total_weight > 0:
                result["overall_progress"] = met_weight / total_weight

            # Include constraint violations
            result["constraint_violations"] = [
                {
                    "constraint_id": v.constraint_id,
                    "description": v.description,
                    "details": v.violation_details,
                    "stream_id": v.stream_id,
                    "timestamp": v.timestamp.isoformat(),
                }
                for v in self._constraint_violations
            ]

            # Add metrics
            result["metrics"] = {
                "total_decisions": self._total_decisions,
                "successful_outcomes": self._successful_outcomes,
                "failed_outcomes": self._failed_outcomes,
                "success_rate": (
                    self._successful_outcomes
                    / max(1, self._successful_outcomes + self._failed_outcomes)
                ),
                "streams_active": len({d.stream_id for d in self._decisions}),
                "executions_total": len({(d.stream_id, d.execution_id) for d in self._decisions}),
            }

            # Determine recommendation
            result["recommendation"] = self._get_recommendation(result)

            # Publish progress event
            if self._event_bus:
                # Get any stream ID for the event
                stream_ids = {d.stream_id for d in self._decisions}
                if stream_ids:
                    await self._event_bus.emit_goal_progress(
                        stream_id=list(stream_ids)[0],
                        progress=result["overall_progress"],
                        criteria_status=result["criteria_status"],
                    )

            return result

    async def _evaluate_criterion(self, criterion: Any) -> CriterionStatus:
        """
        Evaluate a single success criterion.

        For metric-based criteria (output_contains/equals/llm_judge/custom),
        this returns the cached criterion.met set by ``evaluate_output``. The
        legacy keyword-heuristic path was removed in favor of
        ``evaluate_criterion`` which dispatches on the actual metric type
        (issue #3900, Phase 1).

        For success_rate criteria, decision outcomes are still used — but
        without the brittle description-keyword filter; we instead consider
        all decisions whose ``active_constraints`` reference this criterion.
        """
        status = CriterionStatus(
            criterion_id=criterion.id,
            description=criterion.description,
            met=bool(getattr(criterion, "met", False)),
            progress=1.0 if getattr(criterion, "met", False) else 0.0,
            evidence=[],
        )

        criterion_type = getattr(criterion, "type", "success_rate")
        if criterion_type != "success_rate":
            # Metric-based criterion: trust the value set by evaluate_output.
            return status

        # Success-rate criterion: aggregate from decisions whose
        # active_constraints reference this criterion id. Falls back to all
        # decisions if no constraint-tagging is in use.
        tagged_decisions = [
            d
            for d in self._decisions
            if criterion.id in str(d.decision.active_constraints)
        ]
        relevant_decisions = tagged_decisions or list(self._decisions)

        if not relevant_decisions:
            # No evidence yet
            return status

        # Calculate success rate for relevant decisions
        outcomes = [d.outcome for d in relevant_decisions if d.outcome is not None]
        if outcomes:
            success_count = sum(1 for o in outcomes if o.success)

            # Progress is computed as raw success rate of decision outcomes.
            status.progress = success_count / len(outcomes)

            # Add evidence
            for d in relevant_decisions[:5]:  # Limit evidence
                if d.outcome:
                    evidence = (
                        f"decision_id={d.decision.id}, "
                        f"intent={d.decision.intent}, "
                        f"result={'success' if d.outcome.success else 'failed'}"
                    )
                    status.evidence.append(evidence)

        # Check if criterion is met based on target
        try:
            target = criterion.target
            if isinstance(target, str) and target.endswith("%"):
                target_value = float(target.rstrip("%")) / 100
                status.met = status.progress >= target_value
            else:
                # For non-percentage targets, consider met if progress > 0.8
                status.met = status.progress >= 0.8
        except (ValueError, AttributeError):
            status.met = status.progress >= 0.8

        return status

    def _is_related_to_criterion(self, decision: Decision, criterion: Any) -> bool:
        """Check if a decision is related to a criterion."""
        # Simple keyword matching
        criterion_keywords = criterion.description.lower().split()
        decision_text = f"{decision.intent} {decision.reasoning}".lower()

        matches = sum(1 for kw in criterion_keywords if kw in decision_text)
        return matches >= 2  # At least 2 keyword matches

    def _get_recommendation(self, result: dict) -> str:
        """Get recommendation based on current progress."""
        progress = result["overall_progress"]
        violations = result["constraint_violations"]

        # Check for hard constraint violations
        hard_violations = [v for v in violations if self._is_hard_constraint(v["constraint_id"])]

        if hard_violations:
            return "adjust"  # Must address violations

        if progress >= 0.95:
            return "complete"  # Goal essentially achieved

        if progress < 0.3 and result["metrics"]["total_decisions"] > 10:
            return "adjust"  # Low progress despite many decisions

        return "continue"

    def _is_hard_constraint(self, constraint_id: str) -> bool:
        """Check if a constraint is a hard constraint."""
        for constraint in self.goal.constraints:
            if constraint.id == constraint_id:
                return constraint.constraint_type == "hard"
        return False

    # === QUERY OPERATIONS ===

    def get_decisions_by_stream(self, stream_id: str) -> list[DecisionRecord]:
        """Get all decisions from a specific stream."""
        return [d for d in self._decisions if d.stream_id == stream_id]

    def get_decisions_by_execution(
        self,
        stream_id: str,
        execution_id: str,
    ) -> list[DecisionRecord]:
        """Get all decisions from a specific execution."""
        return [
            d
            for d in self._decisions
            if d.stream_id == stream_id and d.execution_id == execution_id
        ]

    def get_recent_decisions(self, limit: int = 10) -> list[DecisionRecord]:
        """Get most recent decisions."""
        return self._decisions[-limit:]

    def get_criterion_status(self, criterion_id: str) -> CriterionStatus | None:
        """Get status of a specific criterion."""
        return self._criterion_status.get(criterion_id)

    def get_stats(self) -> dict:
        """Get aggregator statistics."""
        return {
            "total_decisions": self._total_decisions,
            "successful_outcomes": self._successful_outcomes,
            "failed_outcomes": self._failed_outcomes,
            "constraint_violations": len(self._constraint_violations),
            "criteria_tracked": len(self._criterion_status),
            "streams_seen": len({d.stream_id for d in self._decisions}),
        }

    # === RESET OPERATIONS ===

    def reset(self) -> None:
        """Reset all aggregated data."""
        self._decisions.clear()
        self._decisions_by_id.clear()
        self._constraint_violations.clear()
        self._total_decisions = 0
        self._successful_outcomes = 0
        self._failed_outcomes = 0
        self._last_failure_report = None
        self._initialize_criteria()
        logger.info("OutcomeAggregator reset")
