"""Single definition of which events belong to a worker vs. the queen.

Two places need this answer and they must never disagree:

* the **wire** — which events the queen's SSE feed ships to the frontend
  (``framework.server.routes_events``);
* the **disk** — which log an event is written to (``EventBus``): the queen's
  ``events.jsonl`` or the worker's own.

Historically only the wire had a policy and the disk had none, which is why
worker chatter ended up inlined in the queen's log where nothing reads it back.
Keeping the predicate here means a change to one is a change to both.

This module deliberately imports nothing from ``event_bus`` — ``event_bus``
imports *it*, so depending on ``EventType`` here would be a cycle. The event
names are therefore plain strings, and ``test_events_policy.py`` asserts every
one of them is a real ``EventType`` value so a rename cannot silently drift.
"""

from __future__ import annotations

# Worker events the queen still owns. These are written to the queen's log (in
# addition to the worker's own) and are never filtered off her SSE feed.
#
# The contract: this set must be sufficient to render a worker's *bubble* — it
# started, it is making progress, it finished with this result — WITHOUT any of
# the per-turn chatter. Details (text deltas, tool calls) are fetched on demand
# when the user opens that specific worker.
#
# PAYMENT_REQUIRED is here for correctness, not for the bubble: a worker that
# hits a 402 emits it so the desktop can reopen the upgrade popup. If it were
# worker-local the user would never see the prompt and the colony would just
# look like it silently stalled.
#
# ESCALATION_REQUESTED is deliberately NOT here: it is routed in-process via a
# colony-filtered subscription, never over the queen's SSE, so adding it would
# put an event on the wire that nothing consumes.
WORKER_META_TYPES = frozenset(
    {
        # started.
        #
        # NOTE: a spawned worker does NOT emit `execution_started` — verified
        # against a real 80-worker colony log, which had 62 node_loop_started,
        # 82 subagent_report and ZERO execution_started on worker streams. Its
        # loop announces itself with `node_loop_started`, so that is the real
        # start signal and it must be here or a running worker has nothing to
        # render a bubble from until it finishes. It is per-node, not per-turn:
        # a couple of events per worker, not a firehose.
        "execution_started",  # kept for the singular/legacy spawn path
        "node_loop_started",
        # progress
        "task_created",
        "task_updated",
        "task_deleted",
        # finished
        "subagent_report",
        "execution_completed",
        "execution_failed",
        "worker_completed",
        "worker_failed",
        # must escape the worker: drives the upgrade popup
        "payment_required",
    }
)

# Back-compat alias — the SSE layer historically called this the allowlist.
WORKER_FANIN_TYPES = WORKER_META_TYPES


def is_worker_stream(stream_id: str | None) -> bool:
    """True if ``stream_id`` belongs to a worker.

    Matches both the bare ``"worker"`` tag used by single-worker spawns and the
    ``"worker:{uuid}"`` tag used by parallel fan-outs.
    """
    return (stream_id or "").startswith("worker")


def is_fanout_worker_stream(stream_id: str | None) -> bool:
    """True only for a *parallel* worker (``"worker:{uuid}"``).

    The bare ``"worker"`` tag (``run_agent_with_input``, one spawn) is
    deliberately excluded: a single worker is one stream, not a fan-out, so it
    was never the bandwidth problem this split exists to solve. Gating it would
    only cost it its bubble — it has no worker directory and no row in the
    workers poll, so there is nothing to rebuild the bubble from.
    """
    return (stream_id or "").startswith("worker:")


def is_worker_local(stream_id: str | None, event_type: str | None) -> bool:
    """True if the event is the worker's own business and the queen does not
    need it — per-turn chatter rather than a meta/lifecycle record.

    This is the predicate for both "drop from the queen's SSE feed unless the
    client explicitly asked to watch this worker" and "write to the worker's
    log, not the queen's".

    Only fan-out workers are gated — see :func:`is_fanout_worker_stream`.
    """
    if not is_fanout_worker_stream(stream_id):
        return False
    return event_type not in WORKER_META_TYPES
