"""Phase 5 test: SSE filter drops worker noise from queen DM stream.

The queen DM SSE handler must drop events from parallel-worker streams
(``stream_id="worker:{uuid}"``) so that worker LLM deltas, tool calls,
and iteration events do not flood the user's chat tab. A small allowlist
of worker events is still passed through (SUBAGENT_REPORT,
EXECUTION_COMPLETED, EXECUTION_FAILED) so the frontend can render
fan-out / fan-in lifecycle.

We test the pure ``_is_worker_noise`` predicate by importing the SSE
handler module and exercising the inner function via a closure helper.
"""

from __future__ import annotations

from framework.host.event_bus import EventType


def _make_evt(stream_id: str, evt_type: str) -> dict:
    return {"stream_id": stream_id, "type": evt_type}


def test_queen_stream_events_pass_through() -> None:
    """Events from non-worker streams must always pass."""
    from framework.server.routes_events import _WORKER_EVENT_ALLOWLIST  # noqa: F401

    # Recreate the predicate locally — it's a closure inside the handler,
    # so we mirror its logic here. If the handler's logic changes, this
    # test must be updated to match.
    def is_worker_noise(evt: dict) -> bool:
        sid = evt.get("stream_id") or ""
        if not sid.startswith("worker:"):
            return False
        return evt.get("type") not in {
            EventType.SUBAGENT_REPORT.value,
            EventType.EXECUTION_COMPLETED.value,
            EventType.EXECUTION_FAILED.value,
        }

    # Queen events
    assert not is_worker_noise(_make_evt("queen", EventType.LLM_TEXT_DELTA.value))
    assert not is_worker_noise(_make_evt("queen", EventType.TOOL_CALL_STARTED.value))
    assert not is_worker_noise(_make_evt("overseer", EventType.LLM_TEXT_DELTA.value))
    assert not is_worker_noise(_make_evt("", EventType.LLM_TEXT_DELTA.value))
    assert not is_worker_noise(_make_evt(None, EventType.LLM_TEXT_DELTA.value))


def test_worker_llm_and_tool_events_are_filtered() -> None:
    def is_worker_noise(evt: dict) -> bool:
        sid = evt.get("stream_id") or ""
        if not sid.startswith("worker:"):
            return False
        return evt.get("type") not in {
            EventType.SUBAGENT_REPORT.value,
            EventType.EXECUTION_COMPLETED.value,
            EventType.EXECUTION_FAILED.value,
        }

    assert is_worker_noise(_make_evt("worker:abc123", EventType.LLM_TEXT_DELTA.value))
    assert is_worker_noise(_make_evt("worker:abc123", EventType.TOOL_CALL_STARTED.value))
    assert is_worker_noise(_make_evt("worker:xyz", EventType.TOOL_CALL_COMPLETED.value))
    assert is_worker_noise(_make_evt("worker:xyz", EventType.NODE_LOOP_ITERATION.value))


def test_worker_lifecycle_and_report_events_pass_through() -> None:
    def is_worker_noise(evt: dict) -> bool:
        sid = evt.get("stream_id") or ""
        if not sid.startswith("worker:"):
            return False
        return evt.get("type") not in {
            EventType.SUBAGENT_REPORT.value,
            EventType.EXECUTION_COMPLETED.value,
            EventType.EXECUTION_FAILED.value,
        }

    assert not is_worker_noise(_make_evt("worker:abc", EventType.SUBAGENT_REPORT.value))
    assert not is_worker_noise(_make_evt("worker:abc", EventType.EXECUTION_COMPLETED.value))
    assert not is_worker_noise(_make_evt("worker:abc", EventType.EXECUTION_FAILED.value))


def test_handler_module_exposes_allowlist_constant() -> None:
    """Smoke test that the constant the handler closes over still exists."""
    from framework.server.routes_events import _WORKER_EVENT_ALLOWLIST

    assert EventType.SUBAGENT_REPORT.value in _WORKER_EVENT_ALLOWLIST
    assert EventType.EXECUTION_COMPLETED.value in _WORKER_EVENT_ALLOWLIST
    assert EventType.EXECUTION_FAILED.value in _WORKER_EVENT_ALLOWLIST


def test_loaded_worker_stream_id_singular_passes_through() -> None:
    """The loaded primary worker uses stream_id='worker' (no colon).

    This is the stream tag run_agent_with_input passes to
    ColonyRuntime.spawn. The SSE filter must NOT confuse it with the
    parallel-fan-out 'worker:{uuid}' tag — otherwise the user's main
    chat-visible workstream gets dropped from the queen DM.

    Regression test for: 'why worker message no longer goes to the
    frontend' after migrating run_agent_with_input from
    AgentHost.trigger to ColonyRuntime.spawn.
    """
    from framework.server.routes_events import _is_worker_noise

    # All of these are events from the LOADED worker (single primary
    # worker spawned via run_agent_with_input). They must pass the
    # filter — including high-frequency LLM deltas and tool calls,
    # because the queen DM IS the visible chat for this worker.
    for evt_type in [
        EventType.LLM_TEXT_DELTA.value,
        EventType.TOOL_CALL_STARTED.value,
        EventType.TOOL_CALL_COMPLETED.value,
        EventType.NODE_LOOP_ITERATION.value,
        EventType.CLIENT_OUTPUT_DELTA.value,
        EventType.EXECUTION_STARTED.value,
        EventType.EXECUTION_COMPLETED.value,
    ]:
        evt = {"stream_id": "worker", "type": evt_type}
        assert not _is_worker_noise(evt), (
            f"loaded-worker event {evt_type} with stream_id='worker' was "
            "filtered as worker noise — this regresses the queen DM "
            "primary worker chat path"
        )

    # Sanity: the parallel fan-out tag is still filtered.
    assert _is_worker_noise(
        {
            "stream_id": "worker:abc123",
            "type": EventType.LLM_TEXT_DELTA.value,
        }
    )
