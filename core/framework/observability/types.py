"""
Event types and data models for the observability framework.

This module defines the data structures used throughout the observability
system for capturing lifecycle events, metrics, and traces.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class HookEventType(StrEnum):
    """Types of events emitted by observability hooks."""

    RUN_START = "run_start"
    RUN_COMPLETE = "run_complete"
    NODE_START = "node_start"
    NODE_COMPLETE = "node_complete"
    NODE_ERROR = "node_error"
    DECISION_MADE = "decision_made"
    TOOL_CALL = "tool_call"
    LLM_CALL = "llm_call"
    EDGE_TRAVERSED = "edge_traversed"
    RETRY_OCCURRED = "retry_occurred"


@dataclass
class RunContext:
    """Context for a single agent run."""

    run_id: str
    goal_id: str
    goal_description: str = ""
    input_data: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""
    execution_id: str = ""
    agent_id: str = ""
    started_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "run_id": self.run_id,
            "goal_id": self.goal_id,
            "goal_description": self.goal_description,
            "input_data": self.input_data,
            "trace_id": self.trace_id,
            "execution_id": self.execution_id,
            "agent_id": self.agent_id,
            "started_at": self.started_at.isoformat(),
        }


@dataclass
class NodeContext:
    """Context for node execution."""

    node_id: str
    node_name: str
    node_type: str
    run_id: str
    input_keys: list[str] = field(default_factory=list)
    output_keys: list[str] = field(default_factory=list)
    input_data: dict[str, Any] = field(default_factory=dict)
    started_at: datetime = field(default_factory=datetime.now)
    iteration: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "node_type": self.node_type,
            "run_id": self.run_id,
            "input_keys": self.input_keys,
            "output_keys": self.output_keys,
            "input_data": self.input_data,
            "started_at": self.started_at.isoformat(),
            "iteration": self.iteration,
        }


@dataclass
class NodeResult:
    """Result of node execution."""

    node_id: str
    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    tokens_used: int = 0
    latency_ms: int = 0
    completed_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "node_id": self.node_id,
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "tokens_used": self.tokens_used,
            "latency_ms": self.latency_ms,
            "completed_at": self.completed_at.isoformat(),
        }


@dataclass
class DecisionData:
    """Data about a decision made by the agent."""

    decision_id: str
    node_id: str
    intent: str
    options: list[dict[str, Any]]
    chosen: str
    reasoning: str
    decision_type: str = "custom"
    success: bool | None = None
    outcome_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "decision_id": self.decision_id,
            "node_id": self.node_id,
            "intent": self.intent,
            "options": self.options,
            "chosen": self.chosen,
            "reasoning": self.reasoning,
            "decision_type": self.decision_type,
            "success": self.success,
            "outcome_summary": self.outcome_summary,
        }


@dataclass
class ToolCallData:
    """Data about a tool call."""

    tool_use_id: str
    tool_name: str
    node_id: str
    args: dict[str, Any] = field(default_factory=dict)
    result: str = ""
    is_error: bool = False
    latency_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "tool_use_id": self.tool_use_id,
            "tool_name": self.tool_name,
            "node_id": self.node_id,
            "args": self.args,
            "result": self.result,
            "is_error": self.is_error,
            "latency_ms": self.latency_ms,
        }


@dataclass
class LLMCallData:
    """Data about an LLM call."""

    call_id: str
    node_id: str
    model: str
    provider: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    latency_ms: int = 0
    stop_reason: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "call_id": self.call_id,
            "node_id": self.node_id,
            "model": self.model,
            "provider": self.provider,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "latency_ms": self.latency_ms,
            "stop_reason": self.stop_reason,
            "error": self.error,
        }


@dataclass
class RunOutcome:
    """Final outcome of a run."""

    run_id: str
    success: bool
    output_data: dict[str, Any] = field(default_factory=dict)
    narrative: str = ""
    total_tokens: int = 0
    total_latency_ms: int = 0
    steps_executed: int = 0
    error: str | None = None
    completed_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "run_id": self.run_id,
            "success": self.success,
            "output_data": self.output_data,
            "narrative": self.narrative,
            "total_tokens": self.total_tokens,
            "total_latency_ms": self.total_latency_ms,
            "steps_executed": self.steps_executed,
            "error": self.error,
            "completed_at": self.completed_at.isoformat(),
        }


@dataclass
class EdgeTraversalData:
    """Data about an edge traversal in the graph."""

    source_node: str
    target_node: str
    condition: str = ""
    run_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "source_node": self.source_node,
            "target_node": self.target_node,
            "condition": self.condition,
            "run_id": self.run_id,
        }


@dataclass
class RetryData:
    """Data about a retry event."""

    node_id: str
    retry_count: int
    max_retries: int
    error: str = ""
    run_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "node_id": self.node_id,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "error": self.error,
            "run_id": self.run_id,
        }
