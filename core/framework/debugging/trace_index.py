"""
TraceIndex schema for debugging traces.

Follows Hive patterns:
- Pydantic BaseModel with Field descriptors
- Computed fields with @computed_field
- JSON serialization

Reference: core/framework/schemas/decision.py
"""

from datetime import datetime

from pydantic import BaseModel, Field, computed_field


class TraceIndex(BaseModel):
    """
    Index entry for a single agent execution trace.

    Stores metadata about a run for fast querying without loading
    full L1/L2/L3 logs.

    Follows Hive pattern: Pydantic BaseModel with Field descriptors
    Reference: framework/schemas/decision.py
    """

    # Core identifiers
    run_id: str = Field(description="Unique run identifier")
    agent_id: str = Field(description="Agent that executed this run")
    session_id: str = Field(description="Session directory name")

    # Execution status
    status: str = Field(description="Run status: 'success' | 'failure' | 'degraded'")
    execution_quality: str = Field(
        default="clean", description="Execution quality: 'clean' | 'degraded' | 'failed'"
    )

    # Performance metrics
    total_latency_ms: int = Field(default=0, description="Total execution time in milliseconds")
    total_input_tokens: int = Field(default=0, description="Total input tokens consumed")
    total_output_tokens: int = Field(default=0, description="Total output tokens generated")
    node_count: int = Field(default=0, description="Number of nodes executed")

    # Error tracking
    error_message: str | None = Field(default=None, description="Error message if run failed")
    failed_node_id: str | None = Field(default=None, description="Node ID where failure occurred")

    # Timestamp
    timestamp: datetime = Field(default_factory=datetime.now, description="Run start timestamp")

    # File paths (stored as strings for JSON serialization)
    summary_path: str = Field(description="Path to L1 summary.json file")
    details_path: str = Field(description="Path to L2 details.jsonl file")
    tool_logs_path: str = Field(description="Path to L3 tool_logs.jsonl file")

    # Node metadata
    node_ids: list[str] = Field(
        default_factory=list, description="List of node IDs executed in this run"
    )

    # Computed fields (following Hive pattern)
    @computed_field
    @property
    def total_tokens(self) -> int:
        """
        Total tokens consumed (input + output).

        Follows Hive pattern: @computed_field decorator
        Reference: framework/schemas/decision.py lines 150-171
        """
        return self.total_input_tokens + self.total_output_tokens

    @computed_field
    @property
    def success_rate(self) -> float:
        """
        Success rate based on status.

        Returns 1.0 for success, 0.0 for failure, accounting for node_count.
        """
        if self.node_count == 0:
            return 0.0
        return 1.0 if self.status == "success" else 0.0
