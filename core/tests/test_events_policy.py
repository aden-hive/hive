"""Worker-vs-queen event policy, and the per-worker log routing it drives.

These tests encode *why* the split exists:

* the queen must keep enough of a worker's events to render its bubble after a
  reload, and must never lose a billing prompt;
* the per-turn chatter must not sit in the queen's log, because nothing reads
  it back from there and — with the runtime on another machine — it is shipped
  over the network on every history fetch.
"""

from __future__ import annotations

import asyncio
import json

from framework.host.event_bus import AgentEvent, EventBus, EventType
from framework.host.events_policy import (
    WORKER_META_TYPES,
    is_worker_local,
    is_worker_stream,
)


def test_meta_types_are_all_real_event_types() -> None:
    """events_policy holds plain strings to avoid an import cycle with
    event_bus. This is the guard that keeps them honest: if an EventType value
    is ever renamed, this fails instead of the policy silently going inert and
    routing a live event type to the wrong log."""
    valid = {e.value for e in EventType}
    unknown = WORKER_META_TYPES - valid
    assert not unknown, f"WORKER_META_TYPES contains non-EventType values: {unknown}"


def test_payment_required_is_never_worker_local() -> None:
    """A worker that hits a 402 must still reach the desktop, or the upgrade
    popup never opens and the colony just looks stalled."""
    assert not is_worker_local("worker:abc", EventType.PAYMENT_REQUIRED.value)


def test_bubble_can_be_rendered_from_meta_alone() -> None:
    """start / progress / finish all survive — that's the whole bubble."""
    for t in (
        EventType.EXECUTION_STARTED,
        EventType.TASK_UPDATED,
        EventType.SUBAGENT_REPORT,
        EventType.EXECUTION_COMPLETED,
        EventType.EXECUTION_FAILED,
    ):
        assert not is_worker_local("worker:abc", t.value), t


def test_chatter_of_a_fanout_worker_is_worker_local() -> None:
    for t in (
        EventType.LLM_TEXT_DELTA,
        EventType.TOOL_CALL_STARTED,
        EventType.TOOL_CALL_COMPLETED,
        EventType.NODE_LOOP_ITERATION,
    ):
        assert is_worker_local("worker:abc", t.value), t


def test_single_spawn_worker_is_never_gated() -> None:
    """The bare "worker" tag (run_agent_with_input) is ONE stream, not a
    fan-out — it was never the bandwidth problem. Gating it would only cost it
    its bubble: it has no worker directory and no row in the workers poll, so
    unlike a fan-out worker there is nothing left to rebuild the bubble from.
    Its chatter is the only thing that renders it."""
    for t in (
        EventType.LLM_TEXT_DELTA,
        EventType.TOOL_CALL_STARTED,
        EventType.NODE_LOOP_ITERATION,
    ):
        assert not is_worker_local("worker", t.value), t


def test_queen_events_are_never_worker_local() -> None:
    assert not is_worker_stream("queen")
    assert not is_worker_local("queen", EventType.LLM_TEXT_DELTA.value)
    assert not is_worker_local(None, EventType.LLM_TEXT_DELTA.value)


def _read(path):
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def test_router_splits_chatter_from_queen_but_keeps_meta(tmp_path) -> None:
    """The load-bearing routing test: after a worker runs, the queen's log has
    the bubble (start + report) and none of the chatter, while the worker's log
    is a complete self-contained record."""
    queen_path = tmp_path / "queen" / "events.jsonl"
    worker_path = tmp_path / "workers" / "w1" / "events.jsonl"

    bus = EventBus()
    bus.set_session_log(queen_path)
    bus.set_worker_log_resolver(lambda sid: worker_path if sid == "worker:w1" else None)

    async def drive():
        async def pub(t, sid, **data):
            await bus.publish(AgentEvent(type=t, stream_id=sid, node_id="n", execution_id="e", data=data))

        await pub(EventType.LLM_TEXT_DELTA, "queen", iteration=1, text="hi")
        await pub(EventType.LLM_TURN_COMPLETE, "queen", iteration=1)
        await pub(EventType.EXECUTION_STARTED, "worker:w1", iteration=1)
        await pub(EventType.LLM_TEXT_DELTA, "worker:w1", iteration=1, text="working")
        await pub(EventType.TOOL_CALL_STARTED, "worker:w1", iteration=1)
        await pub(EventType.LLM_TURN_COMPLETE, "worker:w1", iteration=1)
        await pub(EventType.SUBAGENT_REPORT, "worker:w1", iteration=1, status="ok")
        bus.close_session_log()

    asyncio.run(drive())

    queen_types = [e["type"] for e in _read(queen_path)]
    worker_types = [e["type"] for e in _read(worker_path)]

    # Queen keeps the bubble...
    assert "execution_started" in queen_types
    assert "subagent_report" in queen_types
    # ...and none of the worker's chatter.
    assert not any(e["type"] in {"llm_text_delta", "tool_call_started"} and e["stream_id"].startswith("worker") for e in _read(queen_path)), (
        f"worker chatter leaked into the queen's log: {queen_types}"
    )
    # Queen's OWN prose is untouched by the routing.
    assert "llm_text_delta" in [e["type"] for e in _read(queen_path) if e["stream_id"] == "queen"]

    # Worker's log is complete: chatter AND its meta.
    assert "llm_text_delta" in worker_types
    assert "tool_call_started" in worker_types
    assert "execution_started" in worker_types
    assert "subagent_report" in worker_types


def test_worker_log_handle_closed_on_report(tmp_path) -> None:
    """SUBAGENT_REPORT fires exactly once per worker — that's what stops the
    handle map from leaking across a 32-worker fan-out."""
    bus = EventBus()
    bus.set_session_log(tmp_path / "queen" / "events.jsonl")
    bus.set_worker_log_resolver(lambda sid: tmp_path / sid.replace(":", "_") / "e.jsonl")

    async def drive():
        async def pub(t, sid):
            await bus.publish(AgentEvent(type=t, stream_id=sid, node_id="n", execution_id="e", data={}))

        await pub(EventType.TOOL_CALL_STARTED, "worker:w1")
        assert "worker:w1" in bus._worker_logs
        await pub(EventType.SUBAGENT_REPORT, "worker:w1")
        assert "worker:w1" not in bus._worker_logs, "worker log handle leaked"

    asyncio.run(drive())


def test_routing_disabled_by_default_is_legacy_behaviour(tmp_path) -> None:
    """With no resolver installed, everything lands in the queen's log exactly
    as it did before the split — this is what makes the flag safe to ship off."""
    queen_path = tmp_path / "events.jsonl"
    bus = EventBus()
    bus.set_session_log(queen_path)

    async def drive():
        await bus.publish(
            AgentEvent(
                type=EventType.TOOL_CALL_STARTED,
                stream_id="worker:w1",
                node_id="n",
                execution_id="e",
                data={},
            )
        )
        bus.close_session_log()

    asyncio.run(drive())
    assert [e["type"] for e in _read(queen_path)] == ["tool_call_started"]


# ── Wire policy: per-worker opt-in subscription ──────────────────────────────


def _evt(stream_id, type_):
    return {"stream_id": stream_id, "type": type_}


def test_watch_opt_in_gates_only_the_chatter_of_unwatched_workers() -> None:
    """The remote-runtime invariant: a worker's per-turn chatter crosses the
    network only when a human is actually looking at THAT worker."""
    from framework.server.routes_events import _parse_watch, is_suppressed_for_client

    watch_all, watched = _parse_watch("worker:w1")
    assert not watch_all and watched == {"worker:w1"}

    def sup(sid, t):
        return is_suppressed_for_client(_evt(sid, t), watch_all, watched)

    # Watched worker → full detail flows.
    assert not sup("worker:w1", "llm_text_delta")
    assert not sup("worker:w1", "tool_call_started")
    # Unwatched worker → chatter is suppressed...
    assert sup("worker:w2", "llm_text_delta")
    assert sup("worker:w2", "tool_call_started")
    # ...but its bubble still renders, and billing still escapes.
    assert not sup("worker:w2", "execution_started")
    assert not sup("worker:w2", "subagent_report")
    assert not sup("worker:w2", "payment_required")
    # Queen is never gated.
    assert not sup("queen", "llm_text_delta")


def test_watch_defaults_to_no_chatter_at_all() -> None:
    """No ?watch= → the default feed carries bubbles only. This is the change
    from the old phase-aware filter, which firehosed every worker in colony
    phase."""
    from framework.server.routes_events import _parse_watch, is_suppressed_for_client

    watch_all, watched = _parse_watch(None)
    assert is_suppressed_for_client(_evt("worker:w1", "llm_text_delta"), watch_all, watched)
    assert not is_suppressed_for_client(_evt("worker:w1", "subagent_report"), watch_all, watched)


def test_watch_star_is_the_debug_escape_hatch() -> None:
    from framework.server.routes_events import _parse_watch, is_suppressed_for_client

    watch_all, watched = _parse_watch("*")
    assert watch_all
    assert not is_suppressed_for_client(_evt("worker:w9", "llm_text_delta"), watch_all, watched)
