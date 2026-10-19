"""Tests for the parallel-worker scheduler.

The scheduler lives on ``ColonyRuntime`` and replaces the old
"reject when oversubscribed" model with a real queue. Tasks beyond
``max_concurrent_workers`` land in ``_pending_queue`` and promote to
running automatically as peers terminate. Cancellation synthesises a
terminal report so the queen never loses a queued worker silently.

These tests exercise the runtime directly — not the queen tool — so
we can drive scheduler edges deterministically.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from framework.agent_loop.types import AgentSpec
from framework.host.colony_runtime import ColonyConfig, ColonyRuntime
from framework.host.event_bus import AgentEvent, EventBus, EventType
from framework.host.worker import WorkerStatus
from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolResult, ToolUse
from framework.llm.stream_events import FinishEvent, TextDeltaEvent, ToolCallEvent
from framework.schemas.goal import Goal

# ---------------------------------------------------------------------------
# Mock LLM that emits a controllable report per task
# ---------------------------------------------------------------------------


class _ControlledReportLLM(LLMProvider):
    """LLM that fires report_to_parent for any task whose key matches.

    Optionally awaits a per-task asyncio.Event before yielding events,
    so tests can keep specific workers stalled while others finish.
    """

    model: str = "mock"

    def __init__(
        self,
        by_task: dict[str, list],
        gates: dict[str, asyncio.Event] | None = None,
    ):
        self.by_task = by_task
        self.gates = gates or {}
        self._used: set[str] = set()

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 4096,
        **kwargs,
    ) -> AsyncIterator:
        first_user = ""
        for m in messages:
            if m.get("role") == "user":
                content = m.get("content", "")
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            content = block.get("text", "")
                            break
                first_user = str(content)
                break
        for key, events in self.by_task.items():
            if key in first_user:
                if key in self._used:
                    yield TextDeltaEvent(content="Done.", snapshot="Done.")
                    yield FinishEvent(
                        stop_reason="stop",
                        input_tokens=1,
                        output_tokens=1,
                        model="mock",
                    )
                    return
                self._used.add(key)
                gate = self.gates.get(key)
                if gate is not None:
                    await gate.wait()
                for ev in events:
                    yield ev
                return

    def complete(self, messages, system="", **kwargs) -> LLMResponse:
        return LLMResponse(content="", model="mock", stop_reason="stop")


def _report(status: str, summary: str, data: dict | None = None) -> list:
    return [
        ToolCallEvent(
            tool_use_id=f"r_{summary}",
            tool_name="report_to_parent",
            tool_input={"status": status, "summary": summary, "data": data or {}},
        ),
        FinishEvent(stop_reason="tool_calls", input_tokens=10, output_tokens=5, model="mock"),
    ]


def _stub_executor(tool_use: ToolUse) -> ToolResult:
    return ToolResult(tool_use_id=tool_use.tool_use_id, content="ok", is_error=False)


def _make_colony(
    tmp_path: Path,
    *,
    max_concurrent: int,
    by_task: dict[str, list],
    gates: dict[str, asyncio.Event] | None = None,
    colony_id: str = "sched_test",
) -> ColonyRuntime:
    bus = EventBus()
    return ColonyRuntime(
        agent_spec=AgentSpec(
            id="t",
            name="t",
            description="t",
            system_prompt="t",
            agent_type="event_loop",
            output_keys=[],
            tool_access_policy="all",
        ),
        goal=Goal(id="g", name="g", description="g"),
        storage_path=tmp_path / "colony",
        llm=_ControlledReportLLM(by_task=by_task, gates=gates),
        tools=[],
        tool_executor=_stub_executor,
        event_bus=bus,
        stream_id=colony_id,
        pipeline_stages=[],
        config=ColonyConfig(max_concurrent_workers=max_concurrent),
    )


# ---------------------------------------------------------------------------
# Capacity admission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_spawn_under_cap_starts_all_running(tmp_path: Path) -> None:
    """When the batch fits under the cap, every worker is RUNNING (not QUEUED)."""
    colony = _make_colony(
        tmp_path,
        max_concurrent=4,
        by_task={f"task-{i}": _report("success", f"{i} done") for i in range(3)},
    )
    await colony.start()
    try:
        ids = await colony.spawn_batch(
            [{"task": f"task-{i}"} for i in range(3)],
        )
        assert len(ids) == 3
        # No queue ever populated.
        assert len(colony._pending_queue) == 0
        # All three workers admitted (their statuses are not QUEUED).
        for wid in ids:
            assert colony._workers[wid].status != WorkerStatus.QUEUED
    finally:
        await colony.stop()


@pytest.mark.asyncio
async def test_spawn_over_cap_queues_excess(tmp_path: Path) -> None:
    """Overflow tasks land in _pending_queue with status=QUEUED."""
    # Cap = 2. Spawn 5 stalled tasks (gates not opened) so we can
    # observe the queued state before any worker terminates.
    gates = {f"task-{i}": asyncio.Event() for i in range(5)}
    colony = _make_colony(
        tmp_path,
        max_concurrent=2,
        by_task={f"task-{i}": _report("success", f"{i} done") for i in range(5)},
        gates=gates,
    )
    await colony.start()
    try:
        ids = await colony.spawn_batch(
            [{"task": f"task-{i}"} for i in range(5)],
        )
        assert len(ids) == 5
        # Right after admission: 2 active (PENDING/RUNNING), 3 queued.
        running = sum(1 for wid in ids if colony._workers[wid].status in (WorkerStatus.PENDING, WorkerStatus.RUNNING))
        queued = sum(1 for wid in ids if colony._workers[wid].status == WorkerStatus.QUEUED)
        assert running == 2
        assert queued == 3
        assert len(colony._pending_queue) == 3
    finally:
        # Open all gates so workers can drain on stop.
        for g in gates.values():
            g.set()
        await colony.stop()


# ---------------------------------------------------------------------------
# Drain on termination
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queued_workers_promote_as_running_peers_finish(tmp_path: Path) -> None:
    """When a running worker terminates, the next queued worker promotes."""
    # Cap=2, 4 tasks. Open task-0's gate first; one of the queued
    # tasks should be promoted and start running.
    gates = {f"task-{i}": asyncio.Event() for i in range(4)}
    colony = _make_colony(
        tmp_path,
        max_concurrent=2,
        by_task={f"task-{i}": _report("success", f"{i} done") for i in range(4)},
        gates=gates,
    )

    reports: list[dict] = []

    async def _on_report(event: AgentEvent) -> None:
        reports.append(event.data or {})

    colony.event_bus.subscribe(
        event_types=[EventType.SUBAGENT_REPORT],
        handler=_on_report,
    )

    await colony.start()
    try:
        await colony.spawn_batch(
            [{"task": f"task-{i}"} for i in range(4)],
        )
        # Initial state: 2 running, 2 queued.
        assert len(colony._pending_queue) == 2

        # Open the first two (running) gates; both finish.
        gates["task-0"].set()
        gates["task-1"].set()
        # Wait for both first-batch reports to land + queue to drain.
        for _ in range(80):
            if len(reports) >= 2 and len(colony._pending_queue) == 0:
                break
            await asyncio.sleep(0.05)
        assert len(reports) == 2, f"expected 2 reports, got {len(reports)}"
        # Drain happened — queue should be empty now, with both
        # previously-queued workers either RUNNING or already terminal.
        assert len(colony._pending_queue) == 0

        # Now open the two newly-promoted gates so they finish too.
        gates["task-2"].set()
        gates["task-3"].set()
        for _ in range(80):
            if len(reports) >= 4:
                break
            await asyncio.sleep(0.05)
        assert len(reports) == 4
        statuses = {r.get("status") for r in reports}
        assert statuses == {"success"}
    finally:
        for g in gates.values():
            g.set()
        await colony.stop()


# ---------------------------------------------------------------------------
# Cancellation synthesis on stop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_colony_stop_synthesises_stopped_report_for_queued(tmp_path: Path) -> None:
    """colony.stop() with queued workers must emit one stopped SUBAGENT_REPORT each."""
    # Cap=1, 3 tasks, gates closed → 1 running, 2 queued. Stop the
    # colony; the 2 queued tasks should get synthetic stopped reports.
    gates = {f"task-{i}": asyncio.Event() for i in range(3)}
    colony = _make_colony(
        tmp_path,
        max_concurrent=1,
        by_task={f"task-{i}": _report("success", f"{i} done") for i in range(3)},
        gates=gates,
    )

    reports: list[dict] = []

    async def _on_report(event: AgentEvent) -> None:
        reports.append(event.data or {})

    colony.event_bus.subscribe(
        event_types=[EventType.SUBAGENT_REPORT],
        handler=_on_report,
    )

    await colony.start()
    ids = await colony.spawn_batch(
        [{"task": f"task-{i}"} for i in range(3)],
    )
    assert len(ids) == 3
    assert len(colony._pending_queue) == 2

    # Open the running task's gate and wait for its success report
    # to arrive before issuing stop — otherwise the stop races the
    # success path and task-0 may end up stopped instead of completed.
    gates["task-0"].set()
    for _ in range(80):
        if any(r.get("status") == "success" for r in reports):
            break
        await asyncio.sleep(0.05)
    # Don't open task-1 / task-2 gates — we want them stuck so stop()
    # has work to cancel.
    await colony.stop()

    stopped = [r for r in reports if r.get("status") == "stopped"]
    success = [r for r in reports if r.get("status") == "success"]
    assert len(stopped) >= 2, f"expected ≥2 stopped, got {len(stopped)}"
    assert len(success) >= 1, f"expected ≥1 success, got {len(success)}"
    # The synthesised stopped reports must carry batch metadata so the
    # queen-side formatter renders correctly.
    for r in stopped:
        # batch_id may be empty (test path bypasses run_worker'
        # batch_id stamping) — but the field MUST be present.
        assert "batch_id" in r
        assert "batch_index" in r
        assert "batch_size" in r


# ---------------------------------------------------------------------------
# batch_remaining: includes both queued + running
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_metadata_on_subagent_report_with_queued_workers(
    tmp_path: Path,
) -> None:
    """SUBAGENT_REPORT events carry batch_id + indices so the queen-side
    formatter can compute batch_remaining correctly. With cap=2 and 4
    tasks, the first running task's report fires while 1 is still
    running and 2 are queued — total batch_remaining (excluding self) = 3.
    """
    gates = {f"t-{i}": asyncio.Event() for i in range(4)}
    colony = _make_colony(
        tmp_path,
        max_concurrent=2,
        by_task={f"t-{i}": _report("success", f"{i} done") for i in range(4)},
        gates=gates,
    )

    reports: list[dict] = []

    async def _on_report(event: AgentEvent) -> None:
        reports.append(event.data or {})

    colony.event_bus.subscribe(
        event_types=[EventType.SUBAGENT_REPORT],
        handler=_on_report,
    )

    await colony.start()
    try:
        ids = await colony.spawn_batch(
            [{"task": f"t-{i}"} for i in range(4)],
        )
        # All four should share one batch_id.
        # Open the first task only; the rest stay running/queued
        # while we capture the report.
        gates["t-0"].set()

        # Wait for one report.
        for _ in range(80):
            if len(reports) >= 1:
                break
            await asyncio.sleep(0.05)
        assert len(reports) >= 1
        first = reports[0]
        # batch_id is present and non-empty (spawn_batch mints one).
        assert isinstance(first.get("batch_id"), str) and first["batch_id"]
        assert first.get("batch_size") == 4
        assert first.get("batch_index") in (1, 2, 3, 4)
        # All four workers carry the same batch_id.
        all_batch_ids = {colony._workers[wid].batch_id for wid in ids}
        assert all_batch_ids == {first["batch_id"]}

        # Open all gates so the test exits cleanly.
        for g in gates.values():
            g.set()
        for _ in range(80):
            if len(reports) >= 4:
                break
            await asyncio.sleep(0.05)
        assert len(reports) == 4
    finally:
        for g in gates.values():
            g.set()
        await colony.stop()


# ---------------------------------------------------------------------------
# Two interleaved batches share one queue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_batches_interleave_in_pending_queue(tmp_path: Path) -> None:
    """Two run_worker calls back-to-back share the same queue.
    Each task carries its own batch_id; FIFO ordering applies across batches.
    """
    gates = {f"x-{i}": asyncio.Event() for i in range(6)}
    colony = _make_colony(
        tmp_path,
        max_concurrent=1,
        by_task={f"x-{i}": _report("success", f"{i} done") for i in range(6)},
        gates=gates,
    )
    await colony.start()
    try:
        # First batch: 3 tasks. cap=1 → 1 running, 2 queued.
        await colony.spawn_batch(
            [{"task": f"x-{i}"} for i in range(3)],
            batch_id="batch_A",
        )
        # Second batch: 3 more. → 0 admitted, 3 queued (already at cap).
        await colony.spawn_batch(
            [{"task": f"x-{i}"} for i in range(3, 6)],
            batch_id="batch_B",
        )
        # Total queued = 5 (2 from A + 3 from B).
        assert len(colony._pending_queue) == 5
        # First-batch IDs precede second-batch IDs in queue order.
        queue_ids = [w.id for w in colony._pending_queue]
        # batch_A ids that ended up queued (last 2) come before any
        # batch_B id.
        a_queued = [w.id for w in colony._pending_queue if w.batch_id == "batch_A"]
        b_queued = [w.id for w in colony._pending_queue if w.batch_id == "batch_B"]
        first_b_idx = queue_ids.index(b_queued[0])
        last_a_idx = queue_ids.index(a_queued[-1])
        assert last_a_idx < first_b_idx, (
            f"FIFO violation: batch_B's first-queued worker ({first_b_idx}) came before batch_A's last-queued worker ({last_a_idx})"
        )
    finally:
        for g in gates.values():
            g.set()
        await colony.stop()
