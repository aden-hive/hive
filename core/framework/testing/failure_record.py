"""
Failure record schema for tracking agent and node failures.

Captures detailed failure information for debugging and pattern analysis.
This enables developers to understand why agents fail and improve reliability.
"""

from datetime import datetime
from enum import Enum
from typing import Any
import uuid

from pydantic import BaseModel, Field


class FailureSeverity(str, Enum):
    """
    Severity level of a failure.
    
    - CRITICAL: Agent completely failed, cannot continue
    - ERROR: Node failed but agent may have continued
    - WARNING: Unexpected behavior but recovered
    """
    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"


class FailureSource(str, Enum):
    """
    Where the failure originated from.
    """
    NODE_EXECUTION = "node_execution"      # LLMNode, FunctionNode, etc.
    GRAPH_EXECUTOR = "graph_executor"      # FlexibleExecutor, Executor
    TOOL_EXECUTION = "tool_execution"      # MCP tool call failed
    VALIDATION = "validation"              # Pydantic/schema validation
    LLM_CALL = "llm_call"                  # LLM API error
    MEMORY = "memory"                      # SharedMemory error
    RUNTIME = "runtime"                    # Runtime-level error
    UNKNOWN = "unknown"


class FailureRecord(BaseModel):
    """
    Record of a single failure for analysis and debugging.
    
    Captures:
    - What failed (node, error type, message)
    - Why it failed (input data, memory state)
    - When/where it failed (execution path, decisions)
    - Environment context (for reproduction)
    
    Example:
        failure = FailureRecord(
            run_id="run_20260125_123456_abc123",
            goal_id="lead_qualifier",
            node_id="budget_analyzer",
            severity=FailureSeverity.ERROR,
            source=FailureSource.NODE_EXECUTION,
            error_type="ValidationError",
            error_message="Missing required field: budget",
            input_data={"lead_name": "Acme Corp"},
        )
    """
    # Unique identifier
    id: str = Field(
        default_factory=lambda: f"fail_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    )
    
    # Run context
    run_id: str = Field(description="ID of the run where failure occurred")
    goal_id: str = Field(description="ID of the goal being pursued")
    node_id: str | None = Field(
        default=None,
        description="ID of the node that failed (if applicable)"
    )
    
    # Failure classification
    severity: FailureSeverity = Field(
        default=FailureSeverity.ERROR,
        description="How severe the failure is"
    )
    source: FailureSource = Field(
        default=FailureSource.UNKNOWN,
        description="Where the failure originated"
    )
    
    # Error details
    error_type: str = Field(description="Exception class name or error type")
    error_message: str = Field(description="Human-readable error message")
    stack_trace: str | None = Field(
        default=None,
        description="Full stack trace for debugging"
    )
    
    # Context that caused failure (for reproduction)
    input_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Input data that was being processed when failure occurred"
    )
    memory_snapshot: dict[str, Any] = Field(
        default_factory=dict,
        description="State of shared memory at time of failure"
    )
    
    # Execution context
    execution_path: list[str] = Field(
        default_factory=list,
        description="Sequence of nodes executed before failure"
    )
    decisions_before_failure: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Decisions made before failure (id, intent, chosen, reasoning)"
    )
    
    # Retry information
    attempt_number: int = Field(
        default=1,
        description="Which attempt this was (if retries enabled)"
    )
    max_attempts: int = Field(
        default=1,
        description="Maximum attempts configured"
    )
    
    # Metadata
    timestamp: datetime = Field(default_factory=datetime.now)
    environment: dict[str, str] = Field(
        default_factory=dict,
        description="Environment info: Python version, OS, package versions"
    )
    
    # Optional: linked to test if failure occurred during test run
    test_id: str | None = Field(
        default=None,
        description="Test ID if failure occurred during test execution"
    )
    
    model_config = {"extra": "allow"}
    
    def summary(self) -> str:
        """Get a one-line summary of the failure."""
        node_info = f" in node '{self.node_id}'" if self.node_id else ""
        return f"[{self.severity.value.upper()}] {self.error_type}{node_info}: {self.error_message[:100]}"
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage/display."""
        return {
            "id": self.id,
            "run_id": self.run_id,
            "goal_id": self.goal_id,
            "node_id": self.node_id,
            "severity": self.severity.value,
            "source": self.source.value,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "timestamp": self.timestamp.isoformat(),
        }


class FailureStats(BaseModel):
    """
    Aggregate statistics about failures for a goal or agent.
    """
    goal_id: str
    total_failures: int = 0
    
    # Counts by category
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_source: dict[str, int] = Field(default_factory=dict)
    by_error_type: dict[str, int] = Field(default_factory=dict)
    by_node: dict[str, int] = Field(default_factory=dict)
    
    # Time range
    first_failure: datetime | None = None
    last_failure: datetime | None = None
    
    # Most common failures
    top_errors: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Most frequent error types with counts"
    )
    top_failing_nodes: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Nodes with most failures"
    )
    
    model_config = {"extra": "allow"}
