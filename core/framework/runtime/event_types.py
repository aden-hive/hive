"""
Event Types - Structured event payloads for agent observability.

Provides strongly-typed event payloads for all agent events.
Used by both EventBus and WebSocket streaming.

Usage:
    from framework.runtime.event_types import (
        NodeStartedEvent, NodeCompletedEvent, DecisionMadeEvent
    )
    
    event = NodeStartedEvent(
        node_id="calculator",
        node_name="Calculator Node",
        node_type="llm_tool_use",
        input_data={"expression": "2 + 2"},
    )
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class BaseEventPayload:
    """Base class for all event payloads."""
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result = {}
        for key, value in self.__dict__.items():
            if isinstance(value, datetime):
                result[key] = value.isoformat()
            elif hasattr(value, 'to_dict'):
                result[key] = value.to_dict()
            else:
                result[key] = value
        return result


# === Node Execution Events ===

@dataclass
class NodeStartedEvent(BaseEventPayload):
    """Emitted when a node begins execution."""
    node_id: str = ""
    node_name: str = ""
    node_type: str = ""
    input_data: dict[str, Any] = field(default_factory=dict)
    step_number: int = 0


@dataclass
class NodeCompletedEvent(BaseEventPayload):
    """Emitted when a node completes execution."""
    node_id: str = ""
    node_name: str = ""
    node_type: str = ""
    success: bool = True
    output_data: dict[str, Any] = field(default_factory=dict)
    tokens_used: int = 0
    latency_ms: int = 0
    step_number: int = 0


@dataclass
class NodeFailedEvent(BaseEventPayload):
    """Emitted when a node fails."""
    node_id: str = ""
    node_name: str = ""
    node_type: str = ""
    error: str = ""
    error_type: str = ""
    retry_count: int = 0
    max_retries: int = 3
    step_number: int = 0


# === Decision Events ===

@dataclass
class DecisionMadeEvent(BaseEventPayload):
    """Emitted when an agent makes a decision."""
    decision_id: str = ""
    node_id: str = ""
    intent: str = ""
    options: list[dict[str, Any]] = field(default_factory=list)
    chosen_option_id: str = ""
    reasoning: str = ""


@dataclass
class DecisionOutcomeEvent(BaseEventPayload):
    """Emitted when a decision outcome is recorded."""
    decision_id: str = ""
    node_id: str = ""
    success: bool = True
    result_summary: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)


# === Tool Events ===

@dataclass 
class ToolCalledEvent(BaseEventPayload):
    """Emitted when a tool is called."""
    tool_name: str = ""
    node_id: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: str = ""


@dataclass
class ToolResultEvent(BaseEventPayload):
    """Emitted when a tool returns a result."""
    tool_name: str = ""
    node_id: str = ""
    call_id: str = ""
    success: bool = True
    result: Any = None
    error: str | None = None
    latency_ms: int = 0


# === Execution Lifecycle Events ===

@dataclass
class ExecutionStartedEvent(BaseEventPayload):
    """Emitted when an execution begins."""
    execution_id: str = ""
    entry_point: str = ""
    goal_id: str = ""
    goal_name: str = ""
    input_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionCompletedEvent(BaseEventPayload):
    """Emitted when an execution completes."""
    execution_id: str = ""
    success: bool = True
    output_data: dict[str, Any] = field(default_factory=dict)
    steps_executed: int = 0
    total_tokens: int = 0
    total_latency_ms: int = 0
    path: list[str] = field(default_factory=list)


@dataclass
class ExecutionFailedEvent(BaseEventPayload):
    """Emitted when an execution fails."""
    execution_id: str = ""
    error: str = ""
    error_type: str = ""
    failed_at_node: str | None = None
    steps_executed: int = 0
    path: list[str] = field(default_factory=list)


@dataclass
class ExecutionPausedEvent(BaseEventPayload):
    """Emitted when execution is paused for HITL."""
    execution_id: str = ""
    paused_at_node: str = ""
    reason: str = ""
    requires_input: bool = False
    input_schema: dict[str, Any] | None = None
    timeout_seconds: int | None = None


@dataclass
class ExecutionResumedEvent(BaseEventPayload):
    """Emitted when a paused execution resumes."""
    execution_id: str = ""
    resumed_from_node: str = ""
    human_input: dict[str, Any] = field(default_factory=dict)


# === Goal Progress Events ===

@dataclass
class GoalProgressEvent(BaseEventPayload):
    """Emitted when goal progress is updated."""
    goal_id: str = ""
    goal_name: str = ""
    overall_progress: float = 0.0  # 0.0 to 1.0
    criteria_progress: dict[str, float] = field(default_factory=dict)
    completed_criteria: list[str] = field(default_factory=list)
    pending_criteria: list[str] = field(default_factory=list)


@dataclass
class ConstraintViolationEvent(BaseEventPayload):
    """Emitted when a constraint is violated."""
    constraint_id: str = ""
    constraint_description: str = ""
    constraint_type: str = ""  # "hard" or "soft"
    violation_details: str = ""
    node_id: str | None = None


# === Guardrail Events ===

@dataclass
class GuardrailCheckEvent(BaseEventPayload):
    """Emitted when a guardrail is checked."""
    guardrail_id: str = ""
    phase: str = ""  # "pre_execution" or "post_execution"
    passed: bool = True
    violation_message: str | None = None
    severity: str | None = None
    node_id: str = ""


# === Memory Events ===

@dataclass
class MemoryWriteEvent(BaseEventPayload):
    """Emitted when memory is written."""
    key: str = ""
    value_type: str = ""  # Type name of the value
    value_preview: str = ""  # Truncated string representation
    node_id: str = ""
    is_shared: bool = True


@dataclass
class MemoryReadEvent(BaseEventPayload):
    """Emitted when memory is read."""
    key: str = ""
    found: bool = True
    node_id: str = ""


# === Stream Events ===

@dataclass
class StreamStartedEvent(BaseEventPayload):
    """Emitted when an execution stream starts."""
    stream_id: str = ""
    entry_point: str = ""
    isolation_level: str = ""
    max_concurrent: int = 0


@dataclass
class StreamStoppedEvent(BaseEventPayload):
    """Emitted when an execution stream stops."""
    stream_id: str = ""
    total_executions: int = 0
    reason: str = ""
