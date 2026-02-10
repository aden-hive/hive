"""Event types for the observability hook system.

Each event dataclass captures the data passed to an ObservabilityHooks method.
These provide a stable contract for exporters and custom hooks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class RunStartEvent:
    """Emitted when a graph run begins."""

    run_id: str
    goal_id: str
    input_data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass(frozen=True)
class NodeStartEvent:
    """Emitted when a node begins execution."""

    run_id: str
    node_id: str
    node_name: str
    node_type: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass(frozen=True)
class NodeCompleteEvent:
    """Emitted when a node finishes successfully."""

    run_id: str
    node_id: str
    node_name: str
    node_type: str
    success: bool
    latency_ms: int = 0
    tokens_used: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass(frozen=True)
class NodeErrorEvent:
    """Emitted when a node fails with an error."""

    run_id: str
    node_id: str
    node_name: str
    node_type: str
    error: str
    stacktrace: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass(frozen=True)
class DecisionEvent:
    """Emitted when the agent records a decision."""

    run_id: str
    decision_id: str
    node_id: str
    intent: str
    chosen: str
    reasoning: str
    options_count: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass(frozen=True)
class ToolCallEvent:
    """Emitted when a tool is invoked during node execution."""

    run_id: str
    node_id: str
    tool_name: str
    tool_input: dict[str, Any] = field(default_factory=dict)
    result: str = ""
    is_error: bool = False
    latency_ms: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass(frozen=True)
class RunCompleteEvent:
    """Emitted when a graph run finishes."""

    run_id: str
    status: str  # "success" | "failure" | "degraded"
    duration_ms: int = 0
    total_nodes_executed: int = 0
    total_tokens: int = 0
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
