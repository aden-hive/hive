"""
Hive agent run lifecycle instrumentation for Langfuse.

Three functions map to Hive's run lifecycle:
  - start_agent_trace  → call at the very start of each agent run
  - log_node_span      → call after every node finishes executing
  - score_agent_run    → call once at the very end to attach a quality score

The Langfuse SDK reads credentials from the environment automatically:
  LANGFUSE_PUBLIC_KEY  — pk-lf-... from your Langfuse dashboard
  LANGFUSE_SECRET_KEY  — sk-lf-... from your Langfuse dashboard
  LANGFUSE_HOST        — https://cloud.langfuse.com (default) or self-hosted URL

No configuration objects need to be passed around; just call get_client() and go.
"""

from __future__ import annotations

from typing import Any

from langfuse import get_client


def start_agent_trace(
    agent_name: str,
    session_id: str,
    input_data: Any,
    user_id: str = "",
    tags: list[str] | None = None,
) -> str:
    """
    Open a new Langfuse trace for a single Hive agent run.

    Call this once at the very start of each agent run before any nodes execute.
    Returns the trace_id, which must be passed to every subsequent
    log_node_span() and score_agent_run() call for this run.

    Args:
        agent_name: Human-readable name for the agent (shown as trace name in UI).
        session_id: Session identifier to group related runs together.
        input_data: The initial input to the agent run (serialisable value).
        user_id: Optional user/tenant ID attached to the trace.
        tags: Optional list of string tags for filtering in the Langfuse UI.

    Returns:
        trace_id (str) — unique identifier for this trace.

    Example:
        trace_id = start_agent_trace(
            agent_name="research-agent",
            session_id="session-42",
            input_data={"query": "Summarise the Q1 earnings report"},
            user_id="user-99",
            tags=["production", "research"],
        )
    """
    lf = get_client()

    trace = lf.trace(
        name=agent_name,
        session_id=session_id,
        input=input_data,
        user_id=user_id or None,
        tags=tags or [],
    )

    # flush() is NOT needed after trace creation — spans carry the trace's
    # context and will be flushed individually. Flushing here would add latency
    # before the first node even runs.
    return trace.id


def log_node_span(
    trace_id: str,
    node_name: str,
    input: Any,
    output: Any,
    model: str = "",
    latency_ms: float = 0.0,
    tokens: dict[str, int] | None = None,
) -> str:
    """
    Log one completed Hive node as a child span under the agent trace.

    Call this immediately after every node finishes executing. Langfuse will
    nest this span visually under the parent trace in the UI.

    Args:
        trace_id: The trace_id returned by start_agent_trace().
        node_name: Name of the node (e.g. "web_search", "summarise").
        input: The node's input payload (serialisable value).
        output: The node's output payload (serialisable value).
        model: Model name used by the node, if any (e.g. "gpt-4o").
        latency_ms: Wall-clock latency of the node in milliseconds.
        tokens: Optional token-count dict, e.g.
                {"input": 512, "output": 128, "total": 640}.

    Returns:
        span_id (str) — the Langfuse observation ID for this span.

    Example:
        span_id = log_node_span(
            trace_id=trace_id,
            node_name="web_search",
            input={"query": "Q1 earnings Tesla"},
            output={"results": ["..."]},
            model="gpt-4o",
            latency_ms=843.2,
            tokens={"input": 320, "output": 95, "total": 415},
        )
    """
    lf = get_client()

    usage = None
    if tokens:
        usage = {
            "input": tokens.get("input", 0),
            "output": tokens.get("output", 0),
            "total": tokens.get("total", tokens.get("input", 0) + tokens.get("output", 0)),
        }

    span = lf.span(
        trace_id=trace_id,
        name=node_name,
        input=input,
        output=output,
        model=model or None,
        # Langfuse expects latency in seconds, so convert from ms
        metadata={"latency_ms": latency_ms},
        usage=usage,
    )

    # CRITICAL: flush after every span so fast-running agents don't lose data.
    # Langfuse batches async by default; without this, spans can be silently
    # dropped when the process exits before the buffer is drained.
    lf.flush()

    return span.id


def score_agent_run(
    trace_id: str,
    score_name: str,
    score_value: float,
    comment: str = "",
) -> str:
    """
    Attach a quality score (0–1) to a completed Hive agent run.

    Call this once at the very end of a run, after all nodes have finished.
    Scores appear on the trace in the Langfuse UI and can be used for
    filtering, dashboards, and automated evaluation pipelines.

    Args:
        trace_id: The trace_id returned by start_agent_trace().
        score_name: Metric name, e.g. "correctness", "helpfulness", "quality".
        score_value: A float in [0, 1] where 1.0 is best.
        comment: Optional human-readable explanation of the score.

    Returns:
        score_id (str) — the Langfuse score ID.

    Example:
        score_id = score_agent_run(
            trace_id=trace_id,
            score_name="quality",
            score_value=0.87,
            comment="Output was accurate and well-structured.",
        )
    """
    if not isinstance(score_value, (int, float)) or not (0.0 <= score_value <= 1.0):
        raise ValueError(
            f"score_value must be a number in [0, 1], got {score_value!r}. "
            "Use 0.0 for worst and 1.0 for best."
        )

    lf = get_client()

    score = lf.score(
        trace_id=trace_id,
        name=score_name,
        value=score_value,
        comment=comment or None,
    )

    # CRITICAL: flush so the score is guaranteed to land in Langfuse even
    # when the agent process exits immediately after this call.
    lf.flush()

    return score.id
