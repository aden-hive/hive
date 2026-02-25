"""
Session State Schema - Unified state for session execution.

This schema consolidates data from Run, ExecutionResult, and runtime logs
into a single source of truth for session status and resumability.
"""

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, computed_field

if TYPE_CHECKING:
    from framework.graph.executor import ExecutionResult
    from framework.schemas.run import Run


class SessionStatus(StrEnum):
    """Status of a session execution."""

    ACTIVE = "active"  # Currently executing
    PAUSED = "paused"  # Waiting for resume (client input, pause node)
    COMPLETED = "completed"  # Finished successfully
    FAILED = "failed"  # Finished with error
    CANCELLED = "cancelled"  # User/system cancelled


class SessionTimestamps(BaseModel):
    """Timestamps tracking session lifecycle."""

    started_at: str  # ISO 8601 format
    updated_at: str  # ISO 8601 format (updated on every state write)
    completed_at: str | None = None
    paused_at_time: str | None = None  # When it was paused

    model_config = {"extra": "allow"}


class SessionProgress(BaseModel):
    """Execution progress tracking."""

    current_node: str | None = None
    paused_at: str | None = None  # Node ID where paused
    resume_from: str | None = None  # Entry point or node ID to resume from
    steps_executed: int = 0
    total_tokens: int = 0
    total_latency_ms: int = 0
    path: list[str] = Field(default_factory=list)  # Node IDs traversed

    # Quality metrics (from ExecutionResult)
    total_retries: int = 0
    nodes_with_failures: list[str] = Field(default_factory=list)
    retry_details: dict[str, int] = Field(default_factory=dict)
    had_partial_failures: bool = False
    execution_quality: str = "clean"  # "clean", "degraded", or "failed"
    node_visit_counts: dict[str, int] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class SessionResult(BaseModel):
    """Final result of session execution."""

    success: bool | None = None  # None if still running
    error: str | None = None
    output: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class SessionMetrics(BaseModel):
    """Execution metrics (from Run.metrics)."""

    decision_count: int = 0
    problem_count: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    nodes_executed: list[str] = Field(default_factory=list)
    edges_traversed: list[str] = Field(default_factory=list)

    model_config = {"extra": "allow"}


class SessionState(BaseModel):
    """
    Complete state for a session execution.

    This is the single source of truth for session status and resumability.
    Consolidates data from ExecutionResult, ExecutionContext, Run, and runtime logs.

    Version History:
    - v1.0: Initial schema (2026-02-06)
    - v1.1: Added checkpoint support (2026-02-08)
    """

    # Schema version for forward/backward compatibility
    schema_version: str = "1.1"

    # Identity
    session_id: str  # Format: session_YYYYMMDD_HHMMSS_{uuid_8char}
    stream_id: str = ""  # Which ExecutionStream created this
    correlation_id: str = ""  # For correlating related executions

    # Status
    status: SessionStatus = SessionStatus.ACTIVE

    # Goal/Agent context
    goal_id: str
    agent_id: str = ""
    entry_point: str = "start"

    # Timestamps
    timestamps: SessionTimestamps

    # Progress
    progress: SessionProgress = Field(default_factory=SessionProgress)

    # Result
    result: SessionResult = Field(default_factory=SessionResult)

    # Memory (for resumability)
    memory: dict[str, Any] = Field(default_factory=dict)

    # Metrics
    metrics: SessionMetrics = Field(default_factory=SessionMetrics)

    # Problems (from Run.problems)
    problems: list[dict[str, Any]] = Field(default_factory=list)

    # Decisions (from Run.decisions - can be large, so store references)
    decisions: list[dict[str, Any]] = Field(default_factory=list)

    # Input data (for debugging/replay)
    input_data: dict[str, Any] = Field(default_factory=dict)

    # Isolation level (from ExecutionContext)
    isolation_level: str = "shared"

    # Checkpointing (for crash recovery and resume-from-failure)
    checkpoint_enabled: bool = False
    latest_checkpoint_id: str | None = None

    model_config = {"extra": "allow"}

    @computed_field
    @property
    def duration_ms(self) -> int:
        """Duration of the session in milliseconds."""
        if not self.timestamps.completed_at:
            return 0
        started = datetime.fromisoformat(self.timestamps.started_at)
        completed = datetime.fromisoformat(self.timestamps.completed_at)
        return int((completed - started).total_seconds() * 1000)

    @computed_field
    @property
    def is_resumable(self) -> bool:
        """Can this session be resumed?

        Every non-completed session is resumable. If resume_from/paused_at
        aren't set, the executor falls back to the graph entry point —
        so we don't gate on those. Even catastrophic failures are resumable.
        """
        return self.status != SessionStatus.COMPLETED

    @computed_field
    @property
    def is_resumable_from_checkpoint(self) -> bool:
        """Can this session be resumed from a checkpoint?"""
        # ANY session with checkpoints can be resumed (not just failed ones)
        # This enables: pause/resume, iterative execution, continuation after completion
        return self.checkpoint_enabled and self.latest_checkpoint_id is not None

    @classmethod
    def from_execution_result(
        cls,
        session_id: str,
        goal_id: str,
        result: "ExecutionResult",
        stream_id: str = "",
        correlation_id: str = "",
        started_at: str = "",
        input_data: dict[str, Any] | None = None,
        agent_id: str = "",
        entry_point: str = "start",
    ) -> "SessionState":
        """Create SessionState from ExecutionResult."""

        now = datetime.now().isoformat()

        # Determine status based on execution result
        if result.paused_at:
            status = SessionStatus.PAUSED
        elif result.success:
            status = SessionStatus.COMPLETED
        else:
            status = SessionStatus.FAILED

        return cls(
            session_id=session_id,
            stream_id=stream_id,
            correlation_id=correlation_id,
            goal_id=goal_id,
            agent_id=agent_id,
            entry_point=entry_point,
            status=status,
            timestamps=SessionTimestamps(
                started_at=started_at or now,
                updated_at=now,
                completed_at=now if not result.paused_at else None,
                paused_at_time=now if result.paused_at else None,
            ),
            progress=SessionProgress(
                current_node=result.paused_at or (result.path[-1] if result.path else None),
                paused_at=result.paused_at,
                resume_from=result.session_state.get("resume_from")
                if result.session_state
                else None,
                steps_executed=result.steps_executed,
                total_tokens=result.total_tokens,
                total_latency_ms=result.total_latency_ms,
                path=result.path,
                total_retries=result.total_retries,
                nodes_with_failures=result.nodes_with_failures,
                retry_details=result.retry_details,
                had_partial_failures=result.had_partial_failures,
                execution_quality=result.execution_quality,
                node_visit_counts=result.node_visit_counts,
            ),
            result=SessionResult(
                success=result.success,
                error=result.error,
                output=result.output,
            ),
            memory=result.session_state.get("memory", {}) if result.session_state else {},
            input_data=input_data or {},
        )

    @classmethod
    def from_legacy_run(cls, run: "Run", session_id: str, stream_id: str = "") -> "SessionState":
        """Create SessionState from legacy Run object."""
        from framework.schemas.run import RunStatus

        now = datetime.now().isoformat()

        # Map RunStatus to SessionStatus
        status_mapping = {
            RunStatus.RUNNING: SessionStatus.ACTIVE,
            RunStatus.COMPLETED: SessionStatus.COMPLETED,
            RunStatus.FAILED: SessionStatus.FAILED,
            RunStatus.CANCELLED: SessionStatus.CANCELLED,
            RunStatus.STUCK: SessionStatus.FAILED,
        }
        status = status_mapping.get(run.status, SessionStatus.FAILED)

        return cls(
            schema_version="1.0",
            session_id=session_id,
            stream_id=stream_id,
            goal_id=run.goal_id,
            status=status,
            timestamps=SessionTimestamps(
                started_at=run.started_at.isoformat(),
                updated_at=now,
                completed_at=run.completed_at.isoformat() if run.completed_at else None,
            ),
            result=SessionResult(
                success=run.status == RunStatus.COMPLETED,
                output=run.output_data,
            ),
            metrics=SessionMetrics(
                decision_count=run.metrics.total_decisions,
                problem_count=len(run.problems),
                total_input_tokens=run.metrics.total_tokens,  # Approximate
                total_output_tokens=0,  # Not tracked in old format
                nodes_executed=run.metrics.nodes_executed,
                edges_traversed=run.metrics.edges_traversed,
            ),
            decisions=[d.model_dump() for d in run.decisions],
            problems=[p.model_dump() for p in run.problems],
            input_data=run.input_data,
        )

    def to_session_state_dict(self) -> dict[str, Any]:
        """Convert to session_state format for GraphExecutor.execute()."""
        # Derive resume target: explicit > last node in path > entry point
        resume_from = (
            self.progress.resume_from
            or self.progress.paused_at
            or (self.progress.path[-1] if self.progress.path else None)
        )
        return {
            "paused_at": resume_from,
            "resume_from": resume_from,
            "memory": self.memory,
            "execution_path": self.progress.path,
            "node_visit_counts": self.progress.node_visit_counts,
        }
