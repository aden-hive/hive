"""RuntimeLogger: captures runtime data during graph execution.

Injected into GraphExecutor as an optional parameter. Each log_step() and
log_node_complete() call writes immediately to disk (JSONL append). Only
the L1 summary is written at end_run() since it aggregates L2 data.

This provides crash resilience — L2 and L3 data survives process death
without needing end_run() to complete.

Usage::

    store = RuntimeLogStore(Path(work_dir) / "runtime_logs")
    runtime_logger = RuntimeLogger(store=store, agent_id="my-agent")
    executor = GraphExecutor(..., runtime_logger=runtime_logger)
    # After execution, logger has persisted all data to store

Safety: ``end_run()`` catches all exceptions internally and logs them via
the Python logger. Logging failure must never kill a successful run.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from framework.observability import get_trace_context
from framework.runtime.runtime_log_schemas import (
    NodeDetail,
    NodeStepLog,
    RunSummaryLog,
    ToolCallLog,
)
from framework.runtime.runtime_log_store import RuntimeLogStore

logger = logging.getLogger(__name__)


class RuntimeLogger:
    """Captures runtime data during graph execution.

    Thread-safe: uses a lock around file appends for parallel node safety.
    """

    def __init__(self, store: RuntimeLogStore, agent_id: str = "") -> None:
        self._store = store
        self._agent_id = agent_id
        self._run_id = ""
        self._goal_id = ""
        self._started_at = ""
        self._logged_node_ids: set[str] = set()
        self._lock = threading.Lock()

    def start_run(self, goal_id: str = "", session_id: str = "") -> str:
        """Start a new run. Called by GraphExecutor at graph start. Returns run_id.

        Args:
            goal_id: Goal ID for this run
            session_id: Optional session ID. If provided, uses it as run_id (for unified sessions).
                       Otherwise generates a new run_id in old format.

        Returns:
            The run_id (same as session_id if provided)
        """
        if session_id:
            self._run_id = session_id
        else:
            ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
            short_uuid = uuid.uuid4().hex[:8]
            self._run_id = f"{ts}_{short_uuid}"

        self._goal_id = goal_id
        self._started_at = datetime.now(UTC).isoformat()
        self._logged_node_ids = set()
        self._store.ensure_run_dir(self._run_id)
        return self._run_id

    def log_step(
        self,
        node_id: str,
        node_type: str,
        step_index: int,
        llm_text: str = "",
        tool_calls: list[dict[str, Any]] | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: int = 0,
        verdict: str = "",
        verdict_feedback: str = "",
        error: str = "",
        stacktrace: str = "",
        is_partial: bool = False,
    ) -> None:
        """Record data for one step within a node.

        Called by any node during execution. Synchronous, appends to JSONL file.

        Args:
            error: Error message if step failed
            stacktrace: Full stack trace if exception occurred
            is_partial: True if step didn't complete normally (e.g., LLM call crashed)
        """
        if tool_calls is None:
            tool_calls = []

        call_logs = []
        for tc in tool_calls:
            call_logs.append(
                ToolCallLog(
                    tool_use_id=tc.get("tool_use_id", ""),
                    tool_name=tc.get("tool_name", ""),
                    tool_input=tc.get("tool_input", {}),
                    result=tc.get("content", ""),
                    is_error=tc.get("is_error", False),
                    start_timestamp=tc.get("start_timestamp", ""),
                    duration_s=tc.get("duration_s", 0.0),
                )
            )

        # OTel / trace context: from observability ContextVar (empty if not set)
        ctx = get_trace_context()
        trace_id = ctx.get("trace_id", "")
        execution_id = ctx.get("execution_id", "")
        span_id = uuid.uuid4().hex[:16]  # OTel 16-hex span_id per step

        step_log = NodeStepLog(
            node_id=node_id,
            node_type=node_type,
            step_index=step_index,
            llm_text=llm_text,
            tool_calls=call_logs,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            verdict=verdict,
            verdict_feedback=verdict_feedback,
            error=error,
            stacktrace=stacktrace,
            is_partial=is_partial,
            trace_id=trace_id,
            span_id=span_id,
            execution_id=execution_id,
        )

        with self._lock:
            self._store.append_step(self._run_id, step_log)

    def log_node_complete(
        self,
        node_id: str,
        node_name: str,
        node_type: str,
        success: bool,
        error: str | None = None,
        stacktrace: str = "",
        total_steps: int = 0,
        tokens_used: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: int = 0,
        attempt: int = 1,
        # EventLoopNode-specific kwargs:
        exit_status: str = "",
        accept_count: int = 0,
        retry_count: int = 0,
        escalate_count: int = 0,
        continue_count: int = 0,
    ) -> None:
        """Record completion of a node.

        Called after each node completes. EventLoopNode calls this with
        verdict counts and exit_status. Other nodes: executor calls this
        from NodeResult data.
        """
        needs_attention = not success
        attention_reasons: list[str] = []
        if not success and error:
            attention_reasons.append(f"Node {node_id} failed: {error}")

        # Enhanced attention flags
        if retry_count > 3:
            needs_attention = True
            attention_reasons.append(f"Excessive retries: {retry_count}")

        if escalate_count > 2:
            needs_attention = True
            attention_reasons.append(f"Excessive escalations: {escalate_count}")

        if latency_ms > 60000:  # > 1 minute
            needs_attention = True
            attention_reasons.append(f"High latency: {latency_ms}ms")

        if tokens_used > 100000:  # High token usage
            needs_attention = True
            attention_reasons.append(f"High token usage: {tokens_used}")

        if total_steps > 20:  # Many iterations
            needs_attention = True
            attention_reasons.append(f"Many iterations: {total_steps}")

        # OTel / trace context for L2 correlation
        ctx = get_trace_context()
        trace_id = ctx.get("trace_id", "")
        span_id = uuid.uuid4().hex[:16]  # Optional node-level span

        detail = NodeDetail(
            node_id=node_id,
            node_name=node_name,
            node_type=node_type,
            success=success,
            error=error,
            stacktrace=stacktrace,
            total_steps=total_steps,
            tokens_used=tokens_used,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            attempt=attempt,
            exit_status=exit_status,
            accept_count=accept_count,
            retry_count=retry_count,
            escalate_count=escalate_count,
            continue_count=continue_count,
            needs_attention=needs_attention,
            attention_reasons=attention_reasons,
            trace_id=trace_id,
            span_id=span_id,
        )

        with self._lock:
            self._store.append_node_detail(self._run_id, detail)
            self._logged_node_ids.add(node_id)

    def ensure_node_logged(
        self,
        node_id: str,
        node_name: str,
        node_type: str,
        success: bool,
        error: str | None = None,
        stacktrace: str = "",
        tokens_used: int = 0,
        latency_ms: int = 0,
    ) -> None:
        """Fallback: ensure a node has an L2 entry.

        Called by executor after each node returns. If node_id already
        appears in _logged_node_ids (because the node called log_node_complete
        itself), this is a no-op. Otherwise appends a basic NodeDetail.
        """
        with self._lock:
            if node_id in self._logged_node_ids:
                return  # Already logged by the node itself

        # Not yet logged — create a basic entry
        self.log_node_complete(
            node_id=node_id,
            node_name=node_name,
            node_type=node_type,
            success=success,
            error=error,
            stacktrace=stacktrace,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
        )

    async def end_run(
        self,
        status: str,
        duration_ms: int,
        node_path: list[str] | None = None,
        execution_quality: str = "",
    ) -> None:
        """Read L2 from disk, aggregate into L1, write summary.json.

        Called by GraphExecutor when graph finishes. Async, writes 1 file.
        Catches all exceptions internally -- logging failure must not
        propagate to the caller.
        """
        try:
            # Read L2 back from disk to aggregate into L1
            node_details = self._store.read_node_details_sync(self._run_id)

            total_input = sum(nd.input_tokens for nd in node_details)
            total_output = sum(nd.output_tokens for nd in node_details)

            needs_attention = any(nd.needs_attention for nd in node_details)
            attention_reasons: list[str] = []
            for nd in node_details:
                attention_reasons.extend(nd.attention_reasons)

            # OTel / trace context for L1 correlation
            ctx = get_trace_context()
            trace_id = ctx.get("trace_id", "")
            execution_id = ctx.get("execution_id", "")

            summary = RunSummaryLog(
                run_id=self._run_id,
                agent_id=self._agent_id,
                goal_id=self._goal_id,
                status=status,
                total_nodes_executed=len(node_details),
                node_path=node_path or [],
                total_input_tokens=total_input,
                total_output_tokens=total_output,
                needs_attention=needs_attention,
                attention_reasons=attention_reasons,
                started_at=self._started_at,
                duration_ms=duration_ms,
                execution_quality=execution_quality,
                trace_id=trace_id,
                execution_id=execution_id,
            )

            await self._store.save_summary(self._run_id, summary)
            logger.info(
                "Runtime logs saved: run_id=%s status=%s nodes=%d",
                self._run_id,
                status,
                len(node_details),
            )
        except Exception:
            logger.exception(
                "Failed to save runtime logs for run_id=%s (non-fatal)",
                self._run_id,
            )
