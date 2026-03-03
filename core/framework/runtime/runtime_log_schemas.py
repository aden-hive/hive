"""Pydantic models for the three-level runtime logging system.

Level 1 - SUMMARY:    Per graph run pass/fail, token counts, timing
Level 2 - DETAILS:    Per node completion results and attention flags
Level 3 - TOOL LOGS:  Per step within any node (tool calls, LLM text, tokens)
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Level 3: Tool logs (most granular) — per step within any node
# ---------------------------------------------------------------------------


class ToolCallLog(BaseModel):
    """A single tool call within a step."""

    tool_use_id: str
    tool_name: str
    tool_input: dict[str, Any] = Field(default_factory=dict)
    result: str = ""
    is_error: bool = False


class NodeStepLog(BaseModel):
    """Full tool and LLM details for one step within a node.

    For EventLoopNode, each iteration is a step. For single-step nodes
    (e.g. RouterNode), step_index is 0.

    OTel-aligned fields (trace_id, span_id, execution_id) enable correlation
    and future OpenTelemetry export without schema changes.
    """

    node_id: str
    node_type: str = ""  # "event_loop" (the only valid type)
    step_index: int = 0  # iteration number for event_loop, 0 for single-step nodes
    llm_text: str = ""
    tool_calls: list[ToolCallLog] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    # EventLoopNode only:
    verdict: str = ""  # "ACCEPT"|"RETRY"|"ESCALATE"|"CONTINUE"
    verdict_feedback: str = ""
    # Error tracking:
    error: str = ""  # Error message if step failed
    stacktrace: str = ""  # Full stack trace if exception occurred
    is_partial: bool = False  # True if step didn't complete normally
    # OTel / trace context (from observability; empty if not set):
    trace_id: str = ""  # OTel trace id (e.g. from set_trace_context)
    span_id: str = ""  # OTel span id (16 hex chars per step)
    parent_span_id: str = ""  # Optional; for nested span hierarchy
    execution_id: str = ""  # Session/run correlation id


# ---------------------------------------------------------------------------
# Level 2: Per-node completion details
# ---------------------------------------------------------------------------


class NodeDetail(BaseModel):
    """Per-node completion result and attention flags.

    OTel-aligned fields (trace_id, span_id) tie L2 to the same trace as L3.
    """

    node_id: str
    node_name: str = ""
    node_type: str = ""
    success: bool = True
    error: str | None = None
    stacktrace: str = ""  # Full stack trace if exception occurred
    total_steps: int = 0
    tokens_used: int = 0  # combined input+output from NodeResult
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    attempt: int = 1  # retry attempt number
    # EventLoopNode-specific:
    exit_status: str = ""  # "success"|"failure"|"stalled"|"escalated"|"paused"|"guard_failure"
    accept_count: int = 0
    retry_count: int = 0
    escalate_count: int = 0
    continue_count: int = 0
    needs_attention: bool = False
    attention_reasons: list[str] = Field(default_factory=list)
    # OTel / trace context (from observability; empty if not set):
    trace_id: str = ""
    span_id: str = ""  # Optional node-level span for hierarchy


# ---------------------------------------------------------------------------
# Level 1: Run summary — one per full graph execution
# ---------------------------------------------------------------------------


class RunSummaryLog(BaseModel):
    """Run-level summary for a full graph execution.

    OTel-aligned fields (trace_id, execution_id) tie L1 to the same trace as L2/L3.
    """

    run_id: str
    agent_id: str = ""
    goal_id: str = ""
    status: str = ""  # "success"|"failure"|"degraded"
    total_nodes_executed: int = 0
    node_path: list[str] = Field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    needs_attention: bool = False
    attention_reasons: list[str] = Field(default_factory=list)
    started_at: str = ""  # ISO timestamp
    duration_ms: int = 0
    execution_quality: str = ""  # "clean"|"degraded"|"failed"
    # OTel / trace context (from observability; empty if not set):
    trace_id: str = ""
    execution_id: str = ""


# ---------------------------------------------------------------------------
# Container models for file serialization
# ---------------------------------------------------------------------------


class RunDetailsLog(BaseModel):
    """Level 2 container: all node details for a run."""

    run_id: str
    nodes: list[NodeDetail] = Field(default_factory=list)


class RunToolLogs(BaseModel):
    """Level 3 container: all step logs for a run."""

    run_id: str
    steps: list[NodeStepLog] = Field(default_factory=list)
