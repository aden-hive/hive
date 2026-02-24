"""
Outcome Aggregator - Aggregates outcomes across streams for goal evaluation.

The goal-driven nature of Hive means we need to track whether
concurrent executions collectively achieve the goal.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from framework.schemas.decision import Decision, Outcome

if TYPE_CHECKING:
    from framework.graph.goal import Goal
    from framework.runtime.event_bus import EventBus

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
    ):
        """
        Initialize outcome aggregator.

        Args:
            goal: The goal to evaluate progress against
            event_bus: Optional event bus for publishing progress events
        """
        self.goal = goal
        self._event_bus = event_bus

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
        This is a heuristic evaluation based on decision outcomes.
        More sophisticated evaluation can be added per criterion type.
        """
        status = CriterionStatus(
            criterion_id=criterion.id,
            description=criterion.description,
            met=False,
            progress=0.0,
            evidence=[],
        )

        # Guard: only apply this heuristic to success-rate criteria
        criterion_type = getattr(criterion, "type", "success_rate")
        if criterion_type != "success_rate":
            return status

        # Get relevant decisions (those mentioning this criterion or related intents)
        relevant_decisions = [
            d
            for d in self._decisions
            if criterion.id in str(d.decision.active_constraints)
            or self._is_related_to_criterion(d.decision, criterion)
        ]

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
        self._initialize_criteria()
        logger.info("OutcomeAggregator reset")
