"""
State Writer - Dual-write adapter for migration period.

Writes execution state to both old (Run/RunSummary) and new (state.json) formats
to maintain backward compatibility during the transition period.
"""

import logging
import os
from datetime import datetime

from framework.schemas.run import Problem, Run, RunMetrics, RunStatus
from framework.schemas.session_state import SessionState, SessionStatus
from framework.storage.concurrent import ConcurrentStorage
from framework.storage.session_store import SessionStore

logger = logging.getLogger(__name__)


class StateWriter:
    """
    Writes execution state to both old and new formats during migration.

    During the dual-write phase:
    - New format (state.json) is written when USE_UNIFIED_SESSIONS=true
    - Old format (Run/RunSummary) is always written for backward compatibility
    """

    def __init__(self, old_storage: ConcurrentStorage, session_store: SessionStore):
        """
        Initialize state writer.

        Args:
            old_storage: ConcurrentStorage for old format (runs/, summaries/)
            session_store: SessionStore for new format (sessions/*/state.json)
        """
        self.old = old_storage
        self.new = session_store
        self.dual_write_enabled = os.getenv("USE_UNIFIED_SESSIONS", "false").lower() == "true"

    async def write_execution_state(
        self,
        session_id: str,
        state: SessionState,
    ) -> None:
        """
        Write execution state to both old and new formats.

        Args:
            session_id: Session ID
            state: SessionState to write
        """
        # Write to new format if enabled
        if self.dual_write_enabled:
            try:
                await self.new.write_state(session_id, state)
                logger.debug(f"Wrote state.json for session {session_id}")
            except Exception as e:
                logger.error(f"Failed to write state.json for {session_id}: {e}")
                # Don't fail - old format is still written

        # Always write to old format for backward compatibility
        try:
            run = self._convert_to_run(state)
            await self.old.save_run(run)
            logger.debug(f"Wrote Run object for session {session_id}")
        except Exception as e:
            logger.error(f"Failed to write Run object for {session_id}: {e}")
            # This is more critical - reraise if old format fails
            raise

    def _convert_to_run(self, state: SessionState) -> Run:
        """
        Convert SessionState to legacy Run object.

        Args:
            state: SessionState to convert

        Returns:
            Run object
        """
        # Map SessionStatus to RunStatus
        status_mapping = {
            SessionStatus.ACTIVE: RunStatus.RUNNING,
            SessionStatus.PAUSED: RunStatus.RUNNING,  # Paused is still "running" in old format
            SessionStatus.COMPLETED: RunStatus.COMPLETED,
            SessionStatus.FAILED: RunStatus.FAILED,
            SessionStatus.CANCELLED: RunStatus.CANCELLED,
        }
        run_status = status_mapping.get(state.status, RunStatus.FAILED)

        # Convert timestamps
        started_at = datetime.fromisoformat(state.timestamps.started_at)
        completed_at = (
            datetime.fromisoformat(state.timestamps.completed_at)
            if state.timestamps.completed_at
            else None
        )

        # Build RunMetrics
        metrics = RunMetrics(
            total_decisions=state.metrics.decision_count,
            successful_decisions=state.metrics.decision_count
            - len(state.progress.nodes_with_failures),  # Approximate
            failed_decisions=len(state.progress.nodes_with_failures),
            total_tokens=state.metrics.total_input_tokens + state.metrics.total_output_tokens,
            total_latency_ms=state.progress.total_latency_ms,
            nodes_executed=state.metrics.nodes_executed,
            edges_traversed=state.metrics.edges_traversed,
        )

        # Convert problems (SessionState stores as dicts, Run expects Problem objects)
        problems = []
        for p_dict in state.problems:
            # Handle both old Problem objects and new dict format
            if isinstance(p_dict, dict):
                problems.append(Problem(**p_dict))
            else:
                problems.append(p_dict)

        # Convert decisions (SessionState stores as dicts, Run expects Decision objects)
        from framework.schemas.decision import Decision

        decisions = []
        for d_dict in state.decisions:
            # Handle both old Decision objects and new dict format
            if isinstance(d_dict, dict):
                try:
                    decisions.append(Decision(**d_dict))
                except Exception:
                    # Skip invalid decisions
                    continue
            else:
                decisions.append(d_dict)

        # Create Run object
        run = Run(
            id=state.session_id,  # Use session_id as run_id
            goal_id=state.goal_id,
            started_at=started_at,
            status=run_status,
            completed_at=completed_at,
            decisions=decisions,
            problems=problems,
            metrics=metrics,
            goal_description="",  # Not stored in SessionState
            input_data=state.input_data,
            output_data=state.result.output,
        )

        return run

    async def read_state(
        self,
        session_id: str,
        prefer_new: bool = True,
    ) -> SessionState | None:
        """
        Read execution state from either format.

        Args:
            session_id: Session ID
            prefer_new: If True, try new format first (default)

        Returns:
            SessionState or None if not found
        """
        if prefer_new:
            # Try new format first
            state = await self.new.read_state(session_id)
            if state:
                return state

        # Fall back to old format
        run = await self.old.load_run(session_id)
        if run:
            return SessionState.from_legacy_run(run, session_id)

        return None
