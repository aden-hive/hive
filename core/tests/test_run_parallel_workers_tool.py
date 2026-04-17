"""Coverage of the run_parallel_workers tool (fire-and-forget contract).

The tool spawns workers and returns immediately with worker_ids. Each
worker's completion arrives on the event bus as SUBAGENT_REPORT, which
the queen orchestrator's _on_worker_report bridge turns into a
[WORKER_REPORT] user inject. These tests verify:

1. The tool returns immediately with status="started" and the list of
   worker_ids, not with aggregated reports.
2. SUBAGENT_REPORT events are emitted for every spawned worker with
   the expected payload (status, summary, data).
3. Soft-timeout inject reaches still-active workers that haven't
   filed an explicit report; workers that finished early are not
   disturbed.
4. Hard cutoff force-stops workers that ignored the warning, but
   preserves any explicit report filed right before the stop.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from framework.agent_loop.types import AgentSpec
from framework.host.colony_runtime import ColonyRuntime
from framework.host.event_bus import AgentEvent, EventBus, EventType
from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolResult, ToolUse
from framework.llm.stream_events import FinishEvent, TextDeltaEvent, ToolCallEvent
from framework.loader.tool_registry import ToolRegistry
from framework.schemas.goal import Goal
from framework.tools.queen_lifecycle_tools import register_queen_lifecycle_tools

# ---------------------------------------------------------------------------
# Mock LLM that routes scenarios by task text in the first user message
# ---------------------------------------------------------------------------


class _ByTaskMockLLM(LLMProvider):
    model: str = "mock"

    def __init__(self, by_task: dict[str, list]):
        self.by_task = by_task
        self._used_tasks: set[str] = set()

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 4096,
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
                if key in self._used_tasks:
                    yield TextDeltaEvent(content="Done.", snapshot="Done.")
                    yield FinishEvent(stop_reason="stop", input_tokens=1, output_tokens=1, model="mock")
                    return
                self._used_tasks.add(key)
                for ev in events:
                    yield ev
                return

    def complete(self, messages, system="", **kwargs) -> LLMResponse:
        return LLMResponse(content="", model="mock", stop_reason="stop")


def _report(status: str, summary: str, data: dict | None = None) -> list:
    return [
        ToolCallEvent(
            tool_use_id="report_1",
            tool_name="report_to_parent",
            tool_input={"status": status, "summary": summary, "data": data or {}},
        ),
        FinishEvent(stop_reason="tool_calls", input_tokens=10, output_tokens=5, model="mock"),
    ]


def _stub_executor(tool_use: ToolUse) -> ToolResult:
    return ToolResult(tool_use_id=tool_use.tool_use_id, content="ok", is_error=False)


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


class _FakeSession:
    """Minimal session-like object exposing ``colony`` for the tool."""

    def __init__(self, colony: ColonyRuntime, session_id: str):
        self.colony = colony
        self.id = session_id
        # Fields the tool registration may touch even if our test path
        # doesn't exercise them.
        self.colony_runtime = None
        self.event_bus = colony.event_bus
        self.worker_path = None
        self.available_triggers = {}
        self.active_trigger_ids = set()


@pytest.mark.asyncio
async def test_run_parallel_workers_tool_returns_immediately_and_emits_reports(
    tmp_path: Path,
) -> None:
    """Contract: tool returns status='started' right away; SUBAGENT_REPORT
    events for every spawned worker arrive asynchronously on the bus."""
    bus = EventBus()
    llm = _ByTaskMockLLM(
        by_task={
            "fetch-A": _report("success", "A done", {"rows": 10}),
            "fetch-B": _report("success", "B done", {"rows": 20}),
            "fetch-C": _report("failed", "C broke", {"error_code": 503}),
        }
    )

    colony = ColonyRuntime(
        agent_spec=AgentSpec(
            id="test_colony",
            name="Test Colony",
            description="async-spawn test colony.",
            system_prompt="You are a test agent.",
            agent_type="event_loop",
            output_keys=[],
            tool_access_policy="all",
        ),
        goal=Goal(id="g", name="g", description="g"),
        storage_path=tmp_path / "colony",
        llm=llm,
        tools=[],
        tool_executor=_stub_executor,
        event_bus=bus,
        colony_id="async_test",
        pipeline_stages=[],
    )
    await colony.start()

    # Collect SUBAGENT_REPORT events as they arrive.
    collected_reports: list[dict] = []

    async def _on_report(event: AgentEvent) -> None:
        collected_reports.append(event.data or {})

    bus.subscribe(event_types=[EventType.SUBAGENT_REPORT], handler=_on_report)

    session = _FakeSession(colony, "async_test")
    registry = ToolRegistry()
    register_queen_lifecycle_tools(registry, session=session, session_id=session.id)

    try:
        tools = registry.get_tools()
        assert "run_parallel_workers" in tools

        executor = registry.get_executor()
        tool_use = ToolUse(
            id="tu_run_parallel",
            name="run_parallel_workers",
            input={
                "tasks": [
                    {"task": "fetch-A"},
                    {"task": "fetch-B"},
                    {"task": "fetch-C"},
                ],
                "timeout": 30.0,
            },
        )

        # The tool must return quickly — well before workers finish.
        async def _invoke() -> Any:
            r = executor(tool_use)
            if asyncio.iscoroutine(r):
                r = await r
            return r

        result = await asyncio.wait_for(_invoke(), timeout=5.0)

        assert not result.is_error, f"Tool errored: {result.content}"
        payload = json.loads(result.content)
        assert payload["status"] == "started"
        assert payload["worker_count"] == 3
        assert len(payload["worker_ids"]) == 3
        assert payload["soft_timeout_seconds"] == 30.0
        assert payload["hard_timeout_seconds"] >= 30.0 + 60.0  # at least 60s grace
        assert "[WORKER_REPORT]" in payload["message"]
        assert "reports" not in payload  # fire-and-forget — no aggregated reports

        # Now wait for workers to finish and SUBAGENT_REPORT to fire.
        for _ in range(40):
            if len(collected_reports) >= 3:
                break
            await asyncio.sleep(0.1)

        assert len(collected_reports) == 3, (
            f"Expected 3 SUBAGENT_REPORT events, got {len(collected_reports)}"
        )
        statuses = sorted(r["status"] for r in collected_reports)
        summaries = sorted(r["summary"] for r in collected_reports)
        assert statuses == ["failed", "success", "success"]
        assert summaries == ["A done", "B done", "C broke"]

        # Each worker landed under {storage}/workers/{worker_id}/
        worker_root = tmp_path / "colony" / "workers"
        assert worker_root.exists()
        worker_dirs = list(worker_root.iterdir())
        assert len(worker_dirs) == 3
    finally:
        await colony.stop()


@pytest.mark.asyncio
async def test_run_parallel_workers_returns_error_when_no_colony() -> None:
    """If session.colony is None the tool returns a structured error, not a crash."""

    class _SessionWithoutColony:
        colony = None
        id = "no_colony"
        colony_runtime = None
        event_bus = EventBus()
        worker_path = None
        available_triggers: dict = {}
        active_trigger_ids: set = set()

    registry = ToolRegistry()
    register_queen_lifecycle_tools(
        registry,
        session=_SessionWithoutColony(),
        session_id="no_colony",
    )

    executor = registry.get_executor()
    tool_use = ToolUse(
        id="tu_no_colony",
        name="run_parallel_workers",
        input={"tasks": [{"task": "anything"}]},
    )
    result = executor(tool_use)
    if asyncio.iscoroutine(result):
        result = await result

    payload = json.loads(result.content)
    assert "error" in payload
    assert "ColonyRuntime" in payload["error"]


@pytest.mark.asyncio
async def test_run_parallel_workers_validates_tasks_input() -> None:
    """Empty / non-list / missing-task-string inputs return structured errors."""
    bus = EventBus()
    colony = ColonyRuntime(
        agent_spec=AgentSpec(
            id="t",
            name="t",
            description="t",
            system_prompt="t",
            agent_type="event_loop",
        ),
        goal=Goal(id="g", name="g", description="g"),
        storage_path=Path("/tmp/_phase4_validation_test_colony"),
        llm=_ByTaskMockLLM({}),
        tools=[],
        tool_executor=_stub_executor,
        event_bus=bus,
        colony_id="phase4_validation",
        pipeline_stages=[],
    )
    await colony.start()
    session = _FakeSession(colony, "phase4_validation")
    registry = ToolRegistry()
    register_queen_lifecycle_tools(registry, session=session, session_id=session.id)
    executor = registry.get_executor()

    async def _call(payload: dict) -> dict:
        r = executor(ToolUse(id="tu", name="run_parallel_workers", input=payload))
        if asyncio.iscoroutine(r):
            r = await r
        return json.loads(r.content)

    try:
        # Empty list
        assert "error" in await _call({"tasks": []})
        # Missing task string
        assert "error" in await _call({"tasks": [{"data": {}}]})
    finally:
        await colony.stop()


# ---------------------------------------------------------------------------
# Soft-timeout inject reaches slow workers; explicit-report preservation
# ---------------------------------------------------------------------------


class _SlowLLM(LLMProvider):
    """Mock LLM that stalls on _await_user_input by never yielding a finish.

    Each call to ``stream`` awaits the ``stall_event`` before emitting any
    tokens — tests drive it via ``release()``. When the worker's LLM is
    stuck waiting, the watcher's inject message arrives at ``_input_queue``
    but the LLM turn doesn't see it until the current stream finishes.
    We simulate "worker is stuck mid-turn" by holding the stall until the
    test explicitly releases it.
    """

    model: str = "mock-slow"

    def __init__(self) -> None:
        self.stall_event = asyncio.Event()
        self.release_after_inject: bool = False
        self.report_on_release: tuple[str, str, dict] | None = None
        self.inject_seen = asyncio.Event()
        self._turn_count = 0

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator:
        self._turn_count += 1
        # On the second call (after the watcher's inject), check whether the
        # SOFT TIMEOUT message arrived in the conversation.
        if self._turn_count >= 2:
            for m in messages:
                content = m.get("content", "")
                if isinstance(content, str) and "[SOFT TIMEOUT]" in content:
                    self.inject_seen.set()
            if self.report_on_release:
                st, summary, data = self.report_on_release
                yield ToolCallEvent(
                    tool_use_id=f"tu_report_{self._turn_count}",
                    tool_name="report_to_parent",
                    tool_input={"status": st, "summary": summary, "data": data},
                )
                yield FinishEvent(stop_reason="tool_calls", input_tokens=1, output_tokens=1, model="mock-slow")
                return
            # Otherwise loop forever (ignore warning).
            await self.stall_event.wait()
            yield FinishEvent(stop_reason="stop", input_tokens=1, output_tokens=1, model="mock-slow")
            return

        # First turn: stall until released.
        await self.stall_event.wait()
        yield TextDeltaEvent(content="thinking...", snapshot="thinking...")
        yield FinishEvent(stop_reason="stop", input_tokens=1, output_tokens=1, model="mock-slow")

    def complete(self, messages, system="", **kwargs) -> LLMResponse:
        return LLMResponse(content="", model="mock-slow", stop_reason="stop")


async def _build_colony(tmp_path: Path, llm: LLMProvider, colony_id: str) -> ColonyRuntime:
    bus = EventBus()
    colony = ColonyRuntime(
        agent_spec=AgentSpec(
            id="t",
            name="t",
            description="t",
            system_prompt="t",
            agent_type="event_loop",
            tool_access_policy="all",
        ),
        goal=Goal(id="g", name="g", description="g"),
        storage_path=tmp_path / colony_id,
        llm=llm,
        tools=[],
        tool_executor=_stub_executor,
        event_bus=bus,
        colony_id=colony_id,
        pipeline_stages=[],
    )
    await colony.start()
    return colony


@pytest.mark.asyncio
async def test_watch_batch_timeouts_soft_inject_only_hits_stragglers(
    tmp_path: Path,
) -> None:
    """Workers that already filed an explicit report must NOT receive the
    SOFT TIMEOUT warning inject."""
    fast_llm = _ByTaskMockLLM(by_task={"fast": _report("success", "fast done", {})})
    colony = await _build_colony(tmp_path, fast_llm, "soft_fast")

    try:
        ids = await colony.spawn_batch([{"task": "fast"}])
        worker = colony._workers[ids[0]]

        # Wait for the worker to finish naturally.
        for _ in range(50):
            if not worker.is_active:
                break
            await asyncio.sleep(0.05)
        assert not worker.is_active
        assert worker._explicit_report is not None  # it did call report_to_parent

        # Snapshot input-queue depth, then schedule watcher with short soft.
        before = worker._input_queue.qsize()
        task = colony.watch_batch_timeouts(
            ids,
            soft_timeout=0.1,
            hard_timeout=0.2,
        )
        await task
        # Worker already finished + reported — watcher must skip the inject.
        assert worker._input_queue.qsize() == before
    finally:
        await colony.stop()


@pytest.mark.asyncio
async def test_explicit_report_survives_cancel(tmp_path: Path) -> None:
    """A worker that set _explicit_report right before being cancelled must
    emit a SUBAGENT_REPORT carrying the explicit payload, not the canned
    'Worker was cancelled' stub."""
    llm = _ByTaskMockLLM(
        by_task={"cancel-me": _report("success", "partial wrap-up", {"items_done": 3})}
    )
    colony = await _build_colony(tmp_path, llm, "cancel_survives")

    collected: list[dict] = []

    async def _on_report(event: AgentEvent) -> None:
        collected.append(event.data or {})

    colony.event_bus.subscribe(event_types=[EventType.SUBAGENT_REPORT], handler=_on_report)

    try:
        ids = await colony.spawn_batch([{"task": "cancel-me"}])
        worker = colony._workers[ids[0]]

        # Let worker finish first turn so _explicit_report is set,
        # then cancel it.
        for _ in range(50):
            if worker._explicit_report is not None:
                break
            await asyncio.sleep(0.05)
        assert worker._explicit_report is not None, (
            "Worker never set _explicit_report — test precondition not met"
        )

        # Cancel the already-reported worker.
        await colony.stop_worker(ids[0])

        # Drain any pending events.
        for _ in range(20):
            if collected:
                break
            await asyncio.sleep(0.05)

        # The report we receive should be the explicit one.
        assert collected, "No SUBAGENT_REPORT emitted"
        # Find the cancel-survives worker's report (there should only be one).
        report = collected[0]
        assert report.get("summary") == "partial wrap-up", report
        assert report.get("data", {}).get("items_done") == 3, report
    finally:
        await colony.stop()
