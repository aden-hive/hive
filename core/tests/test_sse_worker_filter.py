"""Phase 5 test: SSE filter drops worker noise from queen DM stream.

The queen DM SSE handler drops events from worker streams — both the
single-worker tag (``stream_id="worker"``) and the parallel-fan-out tag
(``stream_id="worker:{uuid}"``) — so that worker LLM deltas, tool calls,
and iteration events do not flood the user's chat when the queen is in
the ``independent`` phase. A small allowlist of worker events still
passes through (SUBAGENT_REPORT, EXECUTION_COMPLETED, EXECUTION_FAILED)
so the frontend can render fan-out / fan-in lifecycle summaries.

Phase-aware behavior (filter on vs off) lives in the SSE handler's
``_should_filter_worker_noise`` closure — tested at the integration
level, not here. This file just exercises the pure
``_is_worker_noise`` predicate.
"""

from __future__ import annotations

from framework.host.event_bus import EventType
from framework.server.routes_events import _is_worker_noise


def _make_evt(stream_id: str | None, evt_type: str) -> dict:
    return {"stream_id": stream_id, "type": evt_type}


def test_queen_stream_events_pass_through() -> None:
    """Events from non-worker streams must always pass."""
    assert not _is_worker_noise(_make_evt("queen", EventType.LLM_TEXT_DELTA.value))
    assert not _is_worker_noise(_make_evt("queen", EventType.TOOL_CALL_STARTED.value))
    assert not _is_worker_noise(_make_evt("overseer", EventType.LLM_TEXT_DELTA.value))
    assert not _is_worker_noise(_make_evt("", EventType.LLM_TEXT_DELTA.value))
    assert not _is_worker_noise(_make_evt(None, EventType.LLM_TEXT_DELTA.value))


def test_worker_llm_and_tool_events_are_filtered() -> None:
    """Worker chatter is noise on both the singular and fan-out tags."""
    # Parallel fan-out tag
    assert _is_worker_noise(_make_evt("worker:abc123", EventType.LLM_TEXT_DELTA.value))
    assert _is_worker_noise(_make_evt("worker:abc123", EventType.TOOL_CALL_STARTED.value))
    assert _is_worker_noise(_make_evt("worker:xyz", EventType.TOOL_CALL_COMPLETED.value))
    assert _is_worker_noise(_make_evt("worker:xyz", EventType.NODE_LOOP_ITERATION.value))
    # Singular primary-worker tag
    assert _is_worker_noise(_make_evt("worker", EventType.LLM_TEXT_DELTA.value))
    assert _is_worker_noise(_make_evt("worker", EventType.TOOL_CALL_STARTED.value))


def test_worker_lifecycle_and_report_events_pass_through() -> None:
    """Allowlisted lifecycle events survive the filter on both tags."""
    # Parallel fan-out tag
    assert not _is_worker_noise(_make_evt("worker:abc", EventType.SUBAGENT_REPORT.value))
    assert not _is_worker_noise(_make_evt("worker:abc", EventType.EXECUTION_COMPLETED.value))
    assert not _is_worker_noise(_make_evt("worker:abc", EventType.EXECUTION_FAILED.value))
    # Singular primary-worker tag
    assert not _is_worker_noise(_make_evt("worker", EventType.SUBAGENT_REPORT.value))
    assert not _is_worker_noise(_make_evt("worker", EventType.EXECUTION_COMPLETED.value))
    assert not _is_worker_noise(_make_evt("worker", EventType.EXECUTION_FAILED.value))


def test_handler_module_exposes_allowlist_constant() -> None:
    """Smoke test that the allowlist constant the predicate closes over still exists."""
    from framework.server.routes_events import _WORKER_EVENT_ALLOWLIST

    assert EventType.SUBAGENT_REPORT.value in _WORKER_EVENT_ALLOWLIST
    assert EventType.EXECUTION_COMPLETED.value in _WORKER_EVENT_ALLOWLIST
    assert EventType.EXECUTION_FAILED.value in _WORKER_EVENT_ALLOWLIST
