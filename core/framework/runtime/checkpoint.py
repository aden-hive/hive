"""
Checkpoint Manager - High-level API for workflow state persistence.

Manages the lifecycle of checkpoints:
- Auto-save after each successful node
- Load checkpoints for recovery
- Cleanup after successful completion

Usage:
    manager = CheckpointManager()
    
    # During execution - save after each node
    manager.save(run_id, step, node_id, memory, ...)
    
    # On recovery - check if run can be resumed
    if manager.can_resume(run_id):
        checkpoint = manager.load_latest(run_id)
        # Resume from checkpoint.next_node_id
    
    # After successful completion
    manager.on_execution_complete(run_id, success=True)
"""

import logging
from pathlib import Path
from typing import Any, Optional

from framework.schemas.checkpoint import (
    Checkpoint,
    CheckpointStatus,
)
from framework.storage.checkpoint_storage import CheckpointStorage

logger = logging.getLogger(__name__)


class CheckpointManager:
    """
    Manages checkpointing for agent execution recovery.
    
    Features:
    - Auto-save after each successful node execution
    - Resume from last successful checkpoint
    - Configurable storage location
    - Optional auto-cleanup on success
    """
    
    def __init__(
        self,
        storage_path: Path | str | None = None,
        enabled: bool = True,
        auto_cleanup: bool = True,
    ):
        """
        Initialize checkpoint manager.
        
        Args:
            storage_path: Where to store checkpoints. Defaults to ~/.aden/checkpoints
            enabled: Whether checkpointing is active. Set False to disable.
            auto_cleanup: Whether to cleanup checkpoints on successful completion.
        """
        self.storage = CheckpointStorage(storage_path)
        self.enabled = enabled
        self.auto_cleanup = auto_cleanup
        self._current_run_id: str | None = None
        
        if enabled:
            logger.debug("CheckpointManager initialized (enabled)")
        else:
            logger.debug("CheckpointManager initialized (disabled)")
    
    def save(
        self,
        run_id: str,
        graph_id: str,
        step_number: int,
        completed_node_id: str,
        next_node_id: str | None,
        path: list[str],
        memory_state: dict[str, Any],
        total_tokens: int = 0,
        total_latency_ms: int = 0,
        input_data: dict[str, Any] | None = None,
        goal_id: str = "",
    ) -> Optional[str]:
        """
        Save a checkpoint after successful node execution.
        
        Returns:
            Filepath where checkpoint was saved, or None if disabled
        """
        if not self.enabled:
            return None
        
        self._current_run_id = run_id
        
        checkpoint = Checkpoint(
            id=f"checkpoint_{step_number:03d}",
            run_id=run_id,
            graph_id=graph_id,
            step_number=step_number,
            completed_node_id=completed_node_id,
            next_node_id=next_node_id,
            path=path.copy(),
            memory_state=memory_state.copy(),
            total_tokens=total_tokens,
            total_latency_ms=total_latency_ms,
            input_data=input_data or {},
            goal_id=goal_id,
        )
        
        filepath = self.storage.save_checkpoint(checkpoint)
        logger.debug(f"💾 Checkpoint saved: step {step_number} after '{completed_node_id}'")
        
        return filepath
    
    def load_latest(self, run_id: str) -> Optional[Checkpoint]:
        """
        Load the most recent checkpoint for a run.
        
        Returns:
            The latest Checkpoint, or None if no checkpoints exist
        """
        checkpoint = self.storage.load_latest_checkpoint(run_id)
        
        if checkpoint:
            logger.info(
                f"📥 Loaded checkpoint: step {checkpoint.step_number} "
                f"at '{checkpoint.completed_node_id}'"
            )
        
        return checkpoint
    
    def can_resume(self, run_id: str) -> bool:
        """
        Check if a run can be resumed from checkpoint.
        
        Returns:
            True if the run has in-progress checkpoints
        """
        if not self.enabled:
            return False
        
        meta = self.storage.get_metadata(run_id)
        return meta is not None and meta.status == CheckpointStatus.IN_PROGRESS
    
    def on_execution_complete(self, run_id: str, success: bool, error: str | None = None) -> None:
        """
        Called when execution completes (success or failure).
        
        Updates checkpoint status and optionally cleans up.
        """
        if not self.enabled:
            return
        
        if success:
            self.storage.update_status(run_id, CheckpointStatus.COMPLETED)
            
            if self.auto_cleanup:
                logger.debug(f"🧹 Cleaning up checkpoints for completed run: {run_id}")
                self.storage.cleanup_run(run_id)
        else:
            self.storage.update_status(
                run_id,
                CheckpointStatus.FAILED,
                error_message=error,
            )
            logger.debug(f"❌ Run failed, checkpoints preserved: {run_id}")
    
    def on_pause(self, run_id: str) -> None:
        """Called when execution pauses (e.g., for HITL approval)."""
        if not self.enabled:
            return
        logger.debug(f"⏸ Run paused, checkpoints preserved: {run_id}")
    
    def cleanup(self, run_id: str) -> bool:
        """Manually cleanup checkpoints for a run."""
        return self.storage.cleanup_run(run_id)
