"""
Checkpoint Schema - Execution state snapshots for resumability.

Checkpoints capture the execution state at strategic points (node boundaries,
iterations) to enable crash recovery and resume-from-failure scenarios.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Checkpoint(BaseModel):
    """
    Single checkpoint in execution timeline.

    Captures complete execution state at a specific point to enable
    resuming from that exact point after failures or pauses.
    """

    # Identity
    checkpoint_id: str  # Format: cp_{type}_{node_id}_{timestamp}
    checkpoint_type: str  # "node_start" | "node_complete" | "loop_iteration"
    session_id: str

    # Timestamps
    created_at: str  # ISO 8601 format

    # Execution state
    current_node: str | None = None
    next_node: str | None = None  # For edge_transition checkpoints
    execution_path: list[str] = Field(default_factory=list)  # Nodes executed so far

    # State snapshots
    shared_memory: dict[str, Any] = Field(default_factory=dict)  # Full SharedMemory._data
    accumulated_outputs: dict[str, Any] = Field(default_factory=dict)  # Outputs accumulated so far

    # Execution metrics (for resuming quality tracking)
    metrics_snapshot: dict[str, Any] = Field(default_factory=dict)

    # Metadata
    is_clean: bool = True  # True if no failures/retries before this checkpoint
    description: str = ""  # Human-readable checkpoint description

    model_config = {"extra": "allow"}

    @classmethod
    def create(
        cls,
        checkpoint_type: str,
        session_id: str,
        current_node: str,
        execution_path: list[str],
        shared_memory: dict[str, Any],
        next_node: str | None = None,
        accumulated_outputs: dict[str, Any] | None = None,
        metrics_snapshot: dict[str, Any] | None = None,
        is_clean: bool = True,
        description: str = "",
    ) -> "Checkpoint":
        """
        Create a new checkpoint with generated ID and timestamp.

        Args:
            checkpoint_type: Type of checkpoint (node_start, node_complete, etc.)
            session_id: Session this checkpoint belongs to
            current_node: Node ID at checkpoint time
            execution_path: List of node IDs executed so far
            shared_memory: Full memory state snapshot
            next_node: Next node to execute (for node_complete checkpoints)
            accumulated_outputs: Outputs accumulated so far
            metrics_snapshot: Execution metrics at checkpoint time
            is_clean: Whether execution was clean up to this point
            description: Human-readable description

        Returns:
            New Checkpoint instance
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        checkpoint_id = f"cp_{checkpoint_type}_{current_node}_{timestamp}"

        if not description:
            description = f"{checkpoint_type.replace('_', ' ').title()}: {current_node}"

        return cls(
            checkpoint_id=checkpoint_id,
            checkpoint_type=checkpoint_type,
            session_id=session_id,
            created_at=datetime.now().isoformat(),
            current_node=current_node,
            next_node=next_node,
            execution_path=execution_path,
            shared_memory=shared_memory,
            accumulated_outputs=accumulated_outputs or {},
            metrics_snapshot=metrics_snapshot or {},
            is_clean=is_clean,
            description=description,
        )


class CheckpointSummary(BaseModel):
    """
    Lightweight checkpoint metadata for index listings.

    Used in checkpoint index to provide fast scanning without
    loading full checkpoint data.
    """

    checkpoint_id: str
    checkpoint_type: str
    created_at: str
    current_node: str | None = None
    next_node: str | None = None
    is_clean: bool = True
    description: str = ""

    model_config = {"extra": "allow"}

    @classmethod
    def from_checkpoint(cls, checkpoint: Checkpoint) -> "CheckpointSummary":
        """Create summary from full checkpoint."""
        return cls(
            checkpoint_id=checkpoint.checkpoint_id,
            checkpoint_type=checkpoint.checkpoint_type,
            created_at=checkpoint.created_at,
            current_node=checkpoint.current_node,
            next_node=checkpoint.next_node,
            is_clean=checkpoint.is_clean,
            description=checkpoint.description,
        )


class CheckpointIndex(BaseModel):
    """
    Manifest of all checkpoints for a session.

    Provides fast lookup and filtering without loading
    full checkpoint files.
    """

    session_id: str
    checkpoints: list[CheckpointSummary] = Field(default_factory=list)
    latest_checkpoint_id: str | None = None
    total_checkpoints: int = 0

    model_config = {"extra": "allow"}

    def add_checkpoint(self, checkpoint: Checkpoint) -> None:
        """Add a checkpoint to the index."""
        summary = CheckpointSummary.from_checkpoint(checkpoint)
        self.checkpoints.append(summary)
        self.latest_checkpoint_id = checkpoint.checkpoint_id
        self.total_checkpoints = len(self.checkpoints)

    def get_checkpoint_summary(self, checkpoint_id: str) -> CheckpointSummary | None:
        """Get checkpoint summary by ID."""
        for summary in self.checkpoints:
            if summary.checkpoint_id == checkpoint_id:
                return summary
        return None

    def filter_by_type(self, checkpoint_type: str) -> list[CheckpointSummary]:
        """Filter checkpoints by type."""
        return [cp for cp in self.checkpoints if cp.checkpoint_type == checkpoint_type]

    def filter_by_node(self, node_id: str) -> list[CheckpointSummary]:
        """Filter checkpoints by current_node."""
        return [cp for cp in self.checkpoints if cp.current_node == node_id]

    def get_clean_checkpoints(self) -> list[CheckpointSummary]:
        """Get all clean checkpoints (no failures before them)."""
        return [cp for cp in self.checkpoints if cp.is_clean]

    def get_latest_clean_checkpoint(self) -> CheckpointSummary | None:
        """Get the most recent clean checkpoint."""
        clean = self.get_clean_checkpoints()
        return clean[-1] if clean else None
