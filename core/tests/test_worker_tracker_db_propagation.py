"""Regression test for ColonyBinding propagation into workers.

Background: a colony queen runs in a DM session whose ``colony_id`` (the
event-bus scope) is the queen's session id, NOT the colony's on-disk
name. A worker that resolved its tracker DB from that scope would land
at ``COLONIES_DIR/<queen-session-id>/tracker/tracker.db`` — a shadow DB
that doesn't have the tables the queen registered under the real colony
name.

The fix collapsed the loose ``colony_id`` / ``tracker_db_path`` fields
into one immutable :class:`ColonyBinding`. ``fork_session_into_colony``
(re-stamped per spawn by ``run_worker``) injects the
serialized binding into every worker's ``input_data``. This test pins
the worker-side half of the contract: that binding must be rehydrated
and stamped onto the ``ToolRegistry`` execution contextvar so tracker
tool executors resolve to the queen's DB — and when no binding was
injected, nothing is stamped (colony tools then refuse rather than
guessing a path from the event-bus scope).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from framework.agent_loop.types import AgentContext, AgentResult, AgentSpec
from framework.host.colony_binding import ColonyBinding
from framework.host.worker import Worker
from framework.loader.tool_registry import _execution_context


class _CapturingAgentLoop:
    """Stub AgentLoop that records the execution contextvar at run time
    and returns a benign success result.

    Mirrors the surface ``Worker.run`` touches: ``execute(ctx)`` and
    an assigned ``_owner_worker`` attribute that the real loop's
    ``report_to_parent`` handler uses.
    """

    def __init__(self) -> None:
        self.captured_ctx: dict[str, Any] | None = None
        self._owner_worker: Any = None

    async def execute(self, ctx: Any) -> AgentResult:
        # Snapshot the contextvar dict as the tool executors would see it.
        self.captured_ctx = dict(_execution_context.get() or {})
        return AgentResult(success=True, output={"ok": True})


def _make_context(
    *,
    agent_id: str,
    input_data: dict[str, Any],
) -> AgentContext:
    """Build a minimal AgentContext shaped like what ColonyRuntime hands
    to a fresh worker. Only the fields ``Worker.run`` reads matter:
    ``agent_id``, ``session_id`` and ``input_data``."""
    return AgentContext(
        runtime=SimpleNamespace(),  # type: ignore[arg-type]
        agent_id=agent_id,
        agent_spec=AgentSpec(
            id=agent_id,
            name=agent_id,
            description="t",
            system_prompt="",
            agent_type="event_loop",
        ),
        input_data=input_data,
        session_id=None,
    )


@pytest.mark.asyncio
async def test_worker_propagates_binding_from_input_data(
    tmp_path: Path,
) -> None:
    """The queen's per-spawn ``binding`` injection in ``input_data`` must
    be rehydrated and land on the contextvar that colony tools read."""
    tracker_path = tmp_path / "linkedin5" / "tracker" / "tracker.db"
    binding = ColonyBinding(
        name="linkedin5",
        dir=tmp_path / "linkedin5",
        tracker_db=tracker_path,
    )
    loop = _CapturingAgentLoop()
    worker = Worker(
        worker_id="w1",
        task="t",
        agent_loop=loop,
        context=_make_context(
            agent_id="w1",
            input_data={"task": "t", "binding": binding.to_dict()},
        ),
        event_bus=None,
    )

    await asyncio.wait_for(worker.run(), timeout=2.0)

    assert loop.captured_ctx is not None
    captured = loop.captured_ctx.get("binding")
    assert isinstance(captured, ColonyBinding), (
        "worker must rehydrate input_data['binding'] and stamp the "
        "ColonyBinding onto the execution contextvar so tracker tools "
        "resolve to the queen's DB"
    )
    # The binding's colony NAME is the on-disk identity, distinct from
    # the queen DM session id that AgentContext.colony_id would carry.
    assert captured.name == "linkedin5"
    assert captured.tracker_db == tracker_path


@pytest.mark.asyncio
async def test_worker_omits_binding_when_input_data_has_none(
    tmp_path: Path,
) -> None:
    """Defensive fallback: when the queen injected no binding, the worker
    must NOT synthesize one. Colony-scoped tools then refuse the call
    rather than guessing a path from the event-bus scope."""
    loop = _CapturingAgentLoop()
    worker = Worker(
        worker_id="w2",
        task="t",
        agent_loop=loop,
        context=_make_context(
            agent_id="w2",
            input_data={"task": "t"},  # no binding
        ),
        event_bus=None,
    )

    await asyncio.wait_for(worker.run(), timeout=2.0)

    assert loop.captured_ctx is not None
    assert "binding" not in loop.captured_ctx, (
        "worker must not stamp a binding onto the contextvar when the "
        "queen didn't inject one — colony tools refuse instead of "
        "resolving a shadow DB under the event-bus scope"
    )
