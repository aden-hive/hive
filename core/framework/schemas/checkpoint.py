"""
Checkpoint Schemas - Data models for workflow state persistence.

Checkpoints capture the execution state after each successful node,
enabling recovery from failures without restarting from scratch.
"""

from datetime import datetime
from typing import Any
from enum import Enum

from pydantic import BaseModel, Field


class CheckpointStatus(str, Enum):
    """Status of a checkpoint run."""
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class Checkpoint(BaseModel):
    """
    Represents a saved execution state after a node completes.
    
    This is the atomic unit of recovery - contains everything needed
    to resume execution from this point.
    
    Example:
        checkpoint = Checkpoint(
            id="checkpoint_003",
            run_id="run_20250123_abc123",
            graph_id="technical-research-agent-graph",
            step_number=3,
            completed_node_id="synthesize-findings",
            next_node_id="format-output",
            path=["analyze-request", "search-web", "synthesize-findings"],
            memory_state={"topic": "AI", "analysis": "...", "search_results": "..."},
        )
    """
    
    # Identity
    id: str = Field(description="Unique checkpoint identifier, e.g., checkpoint_001")
    run_id: str = Field(description="ID of the execution run")
    graph_id: str = Field(description="ID of the graph being executed")
    
    # Execution state
    step_number: int = Field(description="Step number when checkpoint was created")
    completed_node_id: str = Field(description="ID of the node that just completed")
    next_node_id: str | None = Field(
        default=None,
        description="ID of the next node to execute (None if terminal)"
    )
    path: list[str] = Field(
        default_factory=list,
        description="List of node IDs executed so far"
    )
    
    # Memory state (the critical data to restore)
    memory_state: dict[str, Any] = Field(
        default_factory=dict,
        description="Complete shared memory state at checkpoint time"
    )
    
    # Metrics accumulated so far
    total_tokens: int = Field(default=0, description="Total tokens used up to this point")
    total_latency_ms: int = Field(default=0, description="Total latency in milliseconds")
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    node_result_success: bool = Field(default=True, description="Whether the node succeeded")
    
    # For recovery context
    input_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Original input data for the run"
    )
    goal_id: str = Field(default="", description="ID of the goal being pursued")
    
    model_config = {"extra": "allow"}


class CheckpointMetadata(BaseModel):
    """
    Metadata about all checkpoints for a run.
    
    Stored separately for quick lookup without loading all checkpoints.
    """
    run_id: str
    graph_id: str
    goal_id: str = ""
    
    # Checkpoint tracking
    total_checkpoints: int = Field(default=0)
    last_checkpoint_id: str = Field(default="")
    last_completed_node: str = Field(default="")
    last_step_number: int = Field(default=0)
    
    # Timing
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    # Status
    status: CheckpointStatus = Field(default=CheckpointStatus.IN_PROGRESS)
    error_message: str | None = Field(default=None)
    
    # Original input for context
    original_input: dict[str, Any] = Field(default_factory=dict)
    
    model_config = {"extra": "allow"}
