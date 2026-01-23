"""
Checkpoint Manager - Orchestrates checkpoint creation and recovery.

The CheckpointManager provides a stateless interface for saving and restoring
execution state. It handles:
- Checkpoint creation from executor state
- Checkpoint persistence via FileStorage
- Recovery logic (loading and formatting checkpoints)
- Retention policies
"""

import logging
from typing import Any
from datetime import datetime

from framework.schemas.checkpoint import Checkpoint, CheckpointConfig, CheckpointMetadata, ExecutorType
from framework.storage.backend import FileStorage
from framework.graph.node import SharedMemory

logger = logging.getLogger(__name__)


class CheckpointManager:
    """
    Manages checkpoint creation and recovery for agent execution.
    
    The manager is stateless - all state is persisted to FileStorage.
    Multiple managers can safely operate on the same storage.
    
    Usage:
        # In executor
        manager = CheckpointManager(storage, config)
        
        # After successful node execution
        checkpoint_id = manager.save_checkpoint(
            run_id=run_id,
            node_id=current_node_id,
            memory=memory,
            metadata={...}
        )
        
        # On failure, recover
        memory_snapshot, resume_node = manager.restore_from_checkpoint(run_id)
    """
    
    def __init__(
        self,
        storage: FileStorage,
        config: CheckpointConfig | None = None,
    ):
        """
        Initialize the checkpoint manager.
        
        Args:
            storage: FileStorage instance for persistence
            config: Configuration for checkpoint behavior (defaults to CheckpointConfig())
        """
        self.storage = storage
        self.config = config or CheckpointConfig()
        self.logger = logging.getLogger(__name__)
    
    def save_checkpoint(
        self,
        run_id: str,
        node_id: str,
        memory: SharedMemory,
        executor_type: ExecutorType = ExecutorType.GRAPH,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """
        Save a checkpoint of current execution state.
        
        Args:
            run_id: The run ID
            node_id: Current node/step ID
            memory: SharedMemory instance to snapshot
            executor_type: Type of executor (graph or flexible)
            metadata: Additional context (path, tokens, latency, etc.)
        
        Returns:
            Checkpoint ID if saved, None if checkpointing disabled
        """
        if not self.config.enabled:
            return None
        
        metadata = metadata or {}
        
        # Generate checkpoint ID
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        checkpoint_id = f"ckpt_{run_id}_{node_id}_{timestamp}"
        
        # Create checkpoint
        checkpoint = Checkpoint(
            id=checkpoint_id,
            run_id=run_id,
            executor_type=executor_type,
            current_node_id=node_id if executor_type == ExecutorType.GRAPH else None,
            current_step_id=node_id if executor_type == ExecutorType.FLEXIBLE else None,
            next_node_id=metadata.get("next_node_id"),
            memory_snapshot=memory.read_all(),
            execution_path=metadata.get("execution_path", []),
            step_number=metadata.get("step_number", 0),
            total_tokens=metadata.get("total_tokens", 0),
            total_latency_ms=metadata.get("total_latency_ms", 0),
            context=metadata.get("context", {}),
        )
        
        # Save to storage
        try:
            self.storage.save_checkpoint(checkpoint)
            self.logger.debug(f"💾 Saved checkpoint {checkpoint_id} at node {node_id}")
            
            # Apply retention policy
            self._apply_retention_policy(run_id)
            
            return checkpoint_id
        except Exception as e:
            self.logger.warning(f"Failed to save checkpoint: {e}")
            return None
    
    def restore_from_checkpoint(
        self,
        run_id: str,
        checkpoint_id: str | None = None,
    ) -> tuple[dict[str, Any], str] | tuple[None, None]:
        """
        Restore execution state from a checkpoint.
        
        Args:
            run_id: The run ID
            checkpoint_id: Specific checkpoint ID, or None for latest
        
        Returns:
            Tuple of (memory_snapshot, resume_node_id) if found, (None, None) otherwise
        """
        if not self.config.enabled or not self.config.auto_recovery:
            return None, None
        
        try:
            # Load checkpoint
            if checkpoint_id:
                checkpoint = self.storage.load_checkpoint(run_id, checkpoint_id)
            else:
                checkpoint = self.storage.load_latest_checkpoint(run_id)
            
            if checkpoint is None:
                self.logger.info(f"No checkpoint found for run {run_id}")
                return None, None
            
            self.logger.info(f"🔄 Restoring from checkpoint {checkpoint.id} at node {checkpoint.node_id}")
            
            # Return memory snapshot and resume node
            resume_node = checkpoint.next_node_id or checkpoint.node_id
            return checkpoint.memory_snapshot, resume_node
            
        except Exception as e:
            self.logger.warning(f"Failed to restore checkpoint: {e}")
            return None, None
    
    def get_checkpoint(
        self,
        run_id: str,
        checkpoint_id: str | None = None,
    ) -> Checkpoint | None:
        """
        Get a checkpoint without restoring it.
        
        Args:
            run_id: The run ID
            checkpoint_id: Specific checkpoint ID, or None for latest
        
        Returns:
            Checkpoint object if found, None otherwise
        """
        try:
            if checkpoint_id:
                return self.storage.load_checkpoint(run_id, checkpoint_id)
            else:
                return self.storage.load_latest_checkpoint(run_id)
        except Exception as e:
            self.logger.warning(f"Failed to get checkpoint: {e}")
            return None
    
    def list_checkpoints(self, run_id: str) -> list[CheckpointMetadata]:
        """
        List all checkpoints for a run.
        
        Args:
            run_id: The run ID
        
        Returns:
            List of checkpoint metadata (sorted by creation time)
        """
        try:
            return self.storage.list_checkpoints(run_id)
        except Exception as e:
            self.logger.warning(f"Failed to list checkpoints: {e}")
            return []
    
    def delete_checkpoints(self, run_id: str) -> int:
        """
        Delete all checkpoints for a run.
        
        Args:
            run_id: The run ID
        
        Returns:
            Number of checkpoints deleted
        """
        try:
            count = self.storage.delete_checkpoints(run_id)
            self.logger.info(f"🗑️ Deleted {count} checkpoints for run {run_id}")
            return count
        except Exception as e:
            self.logger.warning(f"Failed to delete checkpoints: {e}")
            return 0
    
    def should_checkpoint(self, step_number: int) -> bool:
        """
        Determine if a checkpoint should be saved based on config.
        
        Args:
            step_number: Current step number
        
        Returns:
            True if checkpoint should be saved
        """
        if not self.config.enabled:
            return False
        
        if self.config.save_frequency == "every_node":
            return True
        elif self.config.save_frequency == "every_n_nodes":
            return step_number % self.config.n_nodes == 0
        
        return False
    
    def _apply_retention_policy(self, run_id: str) -> None:
        """Apply retention policy to limit checkpoint count."""
        if self.config.retention_strategy == "all":
            return
        
        try:
            checkpoints = self.storage.list_checkpoints(run_id)
            
            if self.config.retention_strategy == "latest_only":
                # Keep only the latest checkpoint
                if len(checkpoints) > 1:
                    for checkpoint_meta in checkpoints[:-1]:
                        checkpoint_path = (
                            self.storage.base_path / "checkpoints" / "by_run" / 
                            run_id / f"{checkpoint_meta.id}.json"
                        )
                        if checkpoint_path.exists():
                            checkpoint_path.unlink()
            
            elif self.config.retention_strategy == "prune_old":
                # Keep only max_checkpoints_per_run most recent
                if len(checkpoints) > self.config.max_checkpoints_per_run:
                    to_delete = checkpoints[:-self.config.max_checkpoints_per_run]
                    for checkpoint_meta in to_delete:
                        checkpoint_path = (
                            self.storage.base_path / "checkpoints" / "by_run" / 
                            run_id / f"{checkpoint_meta.id}.json"
                        )
                        if checkpoint_path.exists():
                            checkpoint_path.unlink()
        
        except Exception as e:
            self.logger.warning(f"Failed to apply retention policy: {e}")
