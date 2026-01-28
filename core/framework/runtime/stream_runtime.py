"""
Stream Runtime - Thread-safe runtime for concurrent executions.

Unlike the original Runtime which has a single _current_run,
StreamRuntime tracks runs by execution_id, allowing concurrent
executions within the same stream without collision.
"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from framework.schemas.decision import Decision, DecisionType, Option, Outcome
from framework.schemas.run import Run, RunStatus
from framework.storage.concurrent import ConcurrentStorage

if TYPE_CHECKING:
    from framework.runtime.outcome_aggregator import OutcomeAggregator

logger = logging.getLogger(__name__)


class StreamRuntime:
    """
    Thread-safe runtime for a single execution stream.

    Key differences from Runtime:
    - Tracks multiple runs concurrently via execution_id
    - Uses ConcurrentStorage for thread-safe persistence
    - Reports decisions to OutcomeAggregator for cross-stream evaluation

    Example:
        runtime = StreamRuntime(
            stream_id="webhook",
            storage=concurrent_storage,
            outcome_aggregator=aggregator,
        )

        # Start a run for a specific execution
        run_id = runtime.start_run(
            execution_id="exec_123",
            goal_id="support-goal",
            goal_description="Handle support tickets",
        )

        # Record decisions (thread-safe)
        decision_id = runtime.decide(
            execution_id="exec_123",
            intent="Classify ticket",
            options=[...],
            chosen="howto",
            reasoning="Question matches how-to pattern",
        )

        # Record outcome
        runtime.record_outcome(
            execution_id="exec_123",
            decision_id=decision_id,
            success=True,
            result={"category": "howto"},
        )

        # End run
        runtime.end_run(
            execution_id="exec_123",
            success=True,
            narrative="Ticket resolved",
        )
    """

    def __init__(
        self,
        stream_id: str,
        storage: ConcurrentStorage,
        outcome_aggregator: "OutcomeAggregator | None" = None,
    ):
        """
        Initialize stream runtime.

        Args:
            stream_id: Unique identifier for this stream
            storage: Concurrent storage backend
            outcome_aggregator: Optional aggregator for cross-stream evaluation
        """
        self.stream_id = stream_id
        self._storage = storage
        self._outcome_aggregator = outcome_aggregator

        # Track runs by execution_id (thread-safe via lock)
        self._runs: dict[str, Run] = {}
        self._run_locks: dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

        # Track current node per execution (for decision context)
        self._current_nodes: dict[str, str] = {}

    # === RUN LIFECYCLE ===

    def start_run(
        self,
        execution_id: str,
        goal_id: str,
        goal_description: str = "",
        input_data: dict[str, Any] | None = None,
    ) -> str:
        """
        Start a new run for an execution.

        Args:
            execution_id: Unique execution identifier
            goal_id: The ID of the goal being pursued
            goal_description: Human-readable description of the goal
            input_data: Initial input to the run

        Returns:
            The run ID
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_id = f"run_{self.stream_id}_{timestamp}_{uuid.uuid4().hex[:8]}"

        run = Run(
            id=run_id,
            goal_id=goal_id,
            goal_description=goal_description,
            input_data=input_data or {},
        )

        self._runs[execution_id] = run
        self._run_locks[execution_id] = asyncio.Lock()
        self._current_nodes[execution_id] = "unknown"

        logger.debug(
            f"Started run {run_id} for execution {execution_id} in stream {self.stream_id}"
        )
        return run_id

    def end_run(
        self,
        execution_id: str,
        success: bool,
        narrative: str = "",
        output_data: dict[str, Any] | None = None,
    ) -> None:
        """
        End a run for an execution.

        Args:
            execution_id: Execution identifier
            success: Whether the run achieved its goal
            narrative: Human-readable summary of what happened
            output_data: Final output of the run
        """
        run = self._runs.get(execution_id)
        if run is None:
            logger.warning(f"end_run called but no run for execution {execution_id}")
            return

        status = RunStatus.COMPLETED if success else RunStatus.FAILED
        run.output_data = output_data or {}
        run.complete(status, narrative)

        # Save to storage asynchronously
        asyncio.create_task(self._save_run(execution_id, run))

        logger.debug(f"Ended run {run.id} for execution {execution_id}: {status.value}")

    async def _save_run(self, execution_id: str, run: Run) -> None:
        """Save run to storage and clean up."""
        try:
            await self._storage.save_run(run)
        except Exception as e:
            logger.error(f"Failed to save run {run.id}: {e}")
        finally:
            # Clean up
            self._runs.pop(execution_id, None)
            self._run_locks.pop(execution_id, None)
            self._current_nodes.pop(execution_id, None)

    def set_node(self, execution_id: str, node_id: str) -> None:
        """Set the current node context for an execution."""
        self._current_nodes[execution_id] = node_id

    def get_run(self, execution_id: str) -> Run | None:
        """Get the current run for an execution."""
        return self._runs.get(execution_id)

    # === DECISION RECORDING ===

    def decide(
        self,
        execution_id: str,
        intent: str,
        options: list[dict[str, Any]],
        chosen: str,
        reasoning: str,
        node_id: str | None = None,
        decision_type: DecisionType = DecisionType.CUSTOM,
        constraints: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """
        Record a decision for a specific execution.

        Thread-safe: Multiple executions can record decisions concurrently.

        Args:
            execution_id: Which execution is making this decision
            intent: What the agent was trying to accomplish
            options: List of options considered
            chosen: ID of the chosen option
            reasoning: Why the agent chose this option
            node_id: Which node made this decision
            decision_type: Type of decision
            constraints: Active constraints that influenced the decision
            context: Additional context available when deciding

        Returns:
            The decision ID, or empty string if no run in progress
        """
        run = self._runs.get(execution_id)
        if run is None:
            logger.warning(f"decide called but no run for execution {execution_id}: {intent}")
            return ""

        # Build Option objects
        option_objects = []
        for opt in options:
            option_objects.append(
                Option(
                    id=opt["id"],
                    description=opt.get("description", ""),
                    action_type=opt.get("action_type", "unknown"),
                    action_params=opt.get("action_params", {}),
                    pros=opt.get("pros", []),
                    cons=opt.get("cons", []),
                    confidence=opt.get("confidence", 0.5),
                )
            )

        # Create decision
        decision_id = f"dec_{len(run.decisions)}"
        current_node = node_id or self._current_nodes.get(execution_id, "unknown")

        decision = Decision(
            id=decision_id,
            node_id=current_node,
            intent=intent,
            decision_type=decision_type,
            options=option_objects,
            chosen_option_id=chosen,
            reasoning=reasoning,
            active_constraints=constraints or [],
            input_context=context or {},
        )

        run.add_decision(decision)

        # Report to outcome aggregator if available
        if self._outcome_aggregator:
            self._outcome_aggregator.record_decision(
                stream_id=self.stream_id,
                execution_id=execution_id,
                decision=decision,
            )

        return decision_id

    def record_outcome(
        self,
        execution_id: str,
        decision_id: str,
        success: bool,
        result: Any = None,
        error: str | None = None,
        summary: str = "",
        state_changes: dict[str, Any] | None = None,
        tokens_used: int = 0,
        latency_ms: int = 0,
    ) -> None:
        """
        Record the outcome of a decision.

        Args:
            execution_id: Which execution
            decision_id: ID returned from decide()
            success: Whether the action succeeded
            result: The actual result/output
            error: Error message if failed
            summary: Human-readable summary of what happened
            state_changes: What state changed as a result
            tokens_used: LLM tokens consumed
            latency_ms: Time taken in milliseconds
        """
        run = self._runs.get(execution_id)
        if run is None:
            logger.warning(f"record_outcome called but no run for execution {execution_id}")
            return

        outcome = Outcome(
            success=success,
            result=result,
            error=error,
            summary=summary,
            state_changes=state_changes or {},
            tokens_used=tokens_used,
            latency_ms=latency_ms,
        )

        run.record_outcome(decision_id, outcome)

        # Report to outcome aggregator if available
        if self._outcome_aggregator:
            self._outcome_aggregator.record_outcome(
                stream_id=self.stream_id,
                execution_id=execution_id,
                decision_id=decision_id,
                outcome=outcome,
            )

    # === PROBLEM RECORDING ===

    def report_problem(
        self,
        execution_id: str,
        severity: str,
        description: str,
        decision_id: str | None = None,
        root_cause: str | None = None,
        suggested_fix: str | None = None,
    ) -> str:
        """
        Report a problem that occurred during an execution.

        Args:
            execution_id: Which execution
            severity: "critical", "warning", or "minor"
            description: What went wrong
            decision_id: Which decision caused this (if known)
            root_cause: Why it went wrong (if known)
            suggested_fix: What might fix it (if known)

        Returns:
            The problem ID, or empty string if no run in progress
        """
        run = self._runs.get(execution_id)
        if run is None:
            logger.warning(
                f"report_problem called but no run for execution {execution_id}: "
                f"[{severity}] {description}"
            )
            return ""

        return run.add_problem(
            severity=severity,
            description=description,
            decision_id=decision_id,
            root_cause=root_cause,
            suggested_fix=suggested_fix,
        )

    # === CONVENIENCE METHODS ===

    def quick_decision(
        self,
        execution_id: str,
        intent: str,
        action: str,
        reasoning: str,
        node_id: str | None = None,
    ) -> str:
        """
        Record a simple decision with a single action.

        Args:
            execution_id: Which execution
            intent: What the agent is trying to do
            action: What it's doing
            reasoning: Why

        Returns:
            The decision ID
        """
        return self.decide(
            execution_id=execution_id,
            intent=intent,
            options=[
                {
                    "id": "action",
                    "description": action,
                    "action_type": "execute",
                }
            ],
            chosen="action",
            reasoning=reasoning,
            node_id=node_id,
        )

    # === STATS AND MONITORING ===

    def get_active_executions(self) -> list[str]:
        """Get list of active execution IDs."""
        return list(self._runs.keys())

    def get_stats(self) -> dict:
        """Get runtime statistics."""
        return {
            "stream_id": self.stream_id,
            "active_executions": len(self._runs),
            "execution_ids": list(self._runs.keys()),
        }


class StreamRuntimeAdapter:
    """
    Adapter to make StreamRuntime compatible with existing Runtime interface.

    This allows StreamRuntime to be used with existing GraphExecutor code
    by providing the same API as Runtime but routing to a specific execution.
    """

    def __init__(self, stream_runtime: StreamRuntime, execution_id: str):
        """
        Create adapter for a specific execution.

        Args:
            stream_runtime: The underlying stream runtime
            execution_id: Which execution this adapter is for
        """
        self._runtime = stream_runtime
        self._execution_id = execution_id
        self._current_node = "unknown"

    # Expose storage for compatibility
    @property
    def storage(self):
        return self._runtime._storage

    @property
    def current_run(self) -> Run | None:
        return self._runtime.get_run(self._execution_id)

    def start_run(
        self,
        goal_id: str,
        goal_description: str = "",
        input_data: dict[str, Any] | None = None,
    ) -> str:
        return self._runtime.start_run(
            execution_id=self._execution_id,
            goal_id=goal_id,
            goal_description=goal_description,
            input_data=input_data,
        )

    def end_run(
        self,
        success: bool,
        narrative: str = "",
        output_data: dict[str, Any] | None = None,
    ) -> None:
        self._runtime.end_run(
            execution_id=self._execution_id,
            success=success,
            narrative=narrative,
            output_data=output_data,
        )

    def set_node(self, node_id: str) -> None:
        self._current_node = node_id
        self._runtime.set_node(self._execution_id, node_id)

    def decide(
        self,
        intent: str,
        options: list[dict[str, Any]],
        chosen: str,
        reasoning: str,
        node_id: str | None = None,
        decision_type: DecisionType = DecisionType.CUSTOM,
        constraints: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        return self._runtime.decide(
            execution_id=self._execution_id,
            intent=intent,
            options=options,
            chosen=chosen,
            reasoning=reasoning,
            node_id=node_id or self._current_node,
            decision_type=decision_type,
            constraints=constraints,
            context=context,
        )

    def record_outcome(
        self,
        decision_id: str,
        success: bool,
        result: Any = None,
        error: str | None = None,
        summary: str = "",
        state_changes: dict[str, Any] | None = None,
        tokens_used: int = 0,
        latency_ms: int = 0,
    ) -> None:
        self._runtime.record_outcome(
            execution_id=self._execution_id,
            decision_id=decision_id,
            success=success,
            result=result,
            error=error,
            summary=summary,
            state_changes=state_changes,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
        )

    def report_problem(
        self,
        severity: str,
        description: str,
        decision_id: str | None = None,
        root_cause: str | None = None,
        suggested_fix: str | None = None,
    ) -> str:
        return self._runtime.report_problem(
            execution_id=self._execution_id,
            severity=severity,
            description=description,
            decision_id=decision_id,
            root_cause=root_cause,
            suggested_fix=suggested_fix,
        )

    def quick_decision(
        self,
        intent: str,
        action: str,
        reasoning: str,
        node_id: str | None = None,
    ) -> str:
        return self._runtime.quick_decision(
            execution_id=self._execution_id,
            intent=intent,
            action=action,
            reasoning=reasoning,
            node_id=node_id or self._current_node,
        )
