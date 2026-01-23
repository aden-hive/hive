"""
Checkpoint Schema - Automatic state persistence for agent execution recovery.

Checkpoints enable automatic recovery from failures by saving execution state
after each successful node/step. This allows resuming from the last known good
state instead of restarting from scratch.
"""

from datetime import datetime
from typing import Any, Literal
from enum import Enum

from pydantic import BaseModel, Field, computed_field


class ExecutorType(str, Enum):
    """Type of executor that created the checkpoint."""
    GRAPH = "graph"
    FLEXIBLE = "flexible"


class CheckpointConfig(BaseModel):
    """
    Configuration for checkpoint behavior.
    
    Controls when and how checkpoints are created and retained.
    """
    enabled: bool = Field(
        default=True,
        description="Enable/disable checkpointing"
    )
    save_frequency: Literal["every_node", "every_n_nodes"] = Field(
        default="every_node",
        description="How often to save checkpoints"
    )
    n_nodes: int = Field(
        default=1,
        description="Save checkpoint every N nodes (if save_frequency='every_n_nodes')"
    )
    auto_recovery: bool = Field(
        default=True,
        description="Automatically recover from latest checkpoint on failure"
    )
    max_checkpoints_per_run: int = Field(
        default=100,
        description="Maximum checkpoints to retain per run"
    )
    retention_strategy: Literal["all", "latest_only", "prune_old"] = Field(
        default="latest_only",
        description="Strategy for checkpoint retention"
    )

    model_config = {"extra": "allow"}


class CheckpointMetadata(BaseModel):
    """
    Lightweight checkpoint metadata for quick listing.
    
    Contains just enough information to identify and select checkpoints
    without loading full checkpoint data.
    """
    id: str
    run_id: str
    executor_type: ExecutorType
    node_id: str
    created_at: datetime
    step_number: int
    total_tokens: int
    total_latency_ms: int

    model_config = {"extra": "allow"}


class Checkpoint(BaseModel):
    """
    A complete checkpoint of agent execution state.
    
    Contains all information needed to resume execution from this point:
    - Memory state (SharedMemory contents)
    - Execution position (current node/step)
    - Execution history (path taken)
    - Performance metrics
    
    Checkpoints are created automatically after successful node/step execution
    and can be used to recover from failures.
    """
    id: str
    run_id: str
    created_at: datetime = Field(default_factory=datetime.now)
    
    # Executor context
    executor_type: ExecutorType
    
    # Position in execution
    current_node_id: str | None = Field(
        default=None,
        description="Current node ID (for GraphExecutor)"
    )
    current_step_id: str | None = Field(
        default=None,
        description="Current step ID (for FlexibleGraphExecutor)"
    )
    next_node_id: str | None = Field(
        default=None,
        description="Next node to execute (for recovery)"
    )
    
    # State snapshot
    memory_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        description="Complete snapshot of SharedMemory state"
    )
    
    # Execution history
    execution_path: list[str] = Field(
        default_factory=list,
        description="Nodes/steps executed up to this point"
    )
    step_number: int = Field(
        default=0,
        description="Step counter for this checkpoint"
    )
    
    # Performance metrics
    total_tokens: int = Field(default=0)
    total_latency_ms: int = Field(default=0)
    
    # Additional context (executor-specific)
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional executor-specific state"
    )
    
    model_config = {"extra": "allow"}
    
    @computed_field
    @property
    def node_id(self) -> str:
        """Get the current node/step ID (unified accessor)."""
        return self.current_node_id or self.current_step_id or "unknown"
    
    def to_metadata(self) -> CheckpointMetadata:
        """Create metadata summary of this checkpoint."""
        return CheckpointMetadata(
            id=self.id,
            run_id=self.run_id,
            executor_type=self.executor_type,
            node_id=self.node_id,
            created_at=self.created_at,
            step_number=self.step_number,
            total_tokens=self.total_tokens,
            total_latency_ms=self.total_latency_ms,
        )
    
    def to_session_state(self) -> dict[str, Any]:
        """
        Convert checkpoint to session_state format.
        
        Returns session_state dict compatible with GraphExecutor.execute()
        and FlexibleGraphExecutor.execute_plan().
        """
        state = {
            "paused_at": self.current_node_id or self.current_step_id,
            "resume_from": self.next_node_id or self.current_node_id or self.current_step_id,
            "memory": self.memory_snapshot.copy(),
            "execution_path": self.execution_path.copy(),
            "checkpoint_id": self.id,
        }
        
        # Add executor-specific context
        state.update(self.context)
        
        return state
