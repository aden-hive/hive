"""Phase 4 test: run_parallel_workers tool fans out through session.colony.

End-to-end coverage of the queen-side parallel-worker tool:

1. Build a real ``ColonyRuntime`` (the Phase 1 + 2 unified runtime).
2. Stand up the queen lifecycle tools registered against a fake session
   that exposes ``session.colony``.
3. Invoke the ``run_parallel_workers`` tool with three task specs whose
   workers each call ``report_to_parent`` with structured payloads.
4. Assert that the tool returns aggregated reports in the same order as
   the input tasks and that all workers ran in parallel under
   ``{storage}/workers/{worker_id}/``.
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
from framework.host.event_bus import EventBus
from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolResult, ToolUse
from framework.llm.stream_events import FinishEvent, ToolCallEvent
from framework.loader.tool_registry import ToolRegistry
from framework.schemas.goal import Goal
from framework.tools.queen_lifecycle_tools import register_queen_lifecycle_tools

# ---------------------------------------------------------------------------
# Mock LLM that routes scenarios by task text in the first user message
# ---------------------------------------------------------------------------


class _ByTaskMockLLM(LLMProvider):
    def __init__(self, by_task: dict[str, list]):
        self.by_task = by_task

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
async def test_run_parallel_workers_tool_fans_out_and_aggregates(
    tmp_path: Path,
) -> None:
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
            description="Phase 4 test colony.",
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
        colony_id="phase4_test",
        pipeline_stages=[],
    )
    await colony.start()

    session = _FakeSession(colony, "phase4_test")
    registry = ToolRegistry()
    register_queen_lifecycle_tools(registry, session=session, session_id=session.id)

    try:
        # Tool exists in the registry
        tools = registry.get_tools()
        assert "run_parallel_workers" in tools

        # Invoke it via the registered executor
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
                "timeout": 10.0,
            },
        )
        result = executor(tool_use)
        if asyncio.iscoroutine(result):
            result = await result

        assert not result.is_error, f"Tool errored: {result.content}"
        payload = json.loads(result.content)
        assert payload["worker_count"] == 3
        reports = payload["reports"]
        assert len(reports) == 3

        # Reports come back in the same order as the input tasks
        statuses = [r["status"] for r in reports]
        summaries = [r["summary"] for r in reports]
        assert statuses == ["success", "success", "failed"]
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
