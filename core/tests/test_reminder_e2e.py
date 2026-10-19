"""End-to-end tests for the framework reminder system.

Drives a real ``AgentLoop.execute()`` with a scripted mock LLM and a
real on-disk task store, then asserts the ``<system-reminder>`` blocks
actually reach the model — at SESSION_START (injected user message) and
at POST_TOOL_USE (appended to a tool result's tail).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from framework.agent_loop.agent_loop import AgentLoop, LoopConfig
from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolResult, ToolUse
from framework.llm.stream_events import FinishEvent, TextDeltaEvent, ToolCallEvent
from framework.orchestrator.node import DataBuffer, NodeContext, NodeSpec
from framework.tasks.tools.names import TASK_WRITE_TOOLS
from framework.tracker.decision_tracker import DecisionTracker

SESSION_ID = "s1"


# ---------------------------------------------------------------------------
# Minimal loop harness (mirrors tests/test_event_loop_node.py)
# ---------------------------------------------------------------------------


class MockStreamingLLM(LLMProvider):
    """Yields one pre-programmed StreamEvent scenario per stream() call."""

    model = "mock"

    def __init__(self, scenarios: list[list]) -> None:
        self.scenarios = scenarios
        self._i = 0
        self.stream_calls: list[dict] = []

    async def stream(self, messages, system="", tools=None, max_tokens=4096, **kw) -> AsyncIterator:
        self.stream_calls.append({"messages": messages, "system": system})
        events = self.scenarios[self._i % len(self.scenarios)]
        self._i += 1
        for ev in events:
            yield ev

    def complete(self, messages, system="", **kw) -> LLMResponse:
        return LLMResponse(content="summary", model="mock", stop_reason="stop")


def _text_turn(text: str) -> list:
    return [
        TextDeltaEvent(content=text, snapshot=text),
        FinishEvent(stop_reason="stop", input_tokens=10, output_tokens=5, model="mock"),
    ]


def _tool_turn(name: str, args: dict, tool_use_id: str) -> list:
    return [
        ToolCallEvent(tool_use_id=tool_use_id, tool_name=name, tool_input=args),
        FinishEvent(stop_reason="tool_calls", input_tokens=10, output_tokens=5, model="mock"),
    ]


def _build_ctx(
    llm: LLMProvider,
    tools: list[Tool] | None = None,
    *,
    task_capable: bool = True,
) -> NodeContext:
    rt = MagicMock(spec=DecisionTracker)
    rt.start_run = MagicMock(return_value="session_20260101_000000_e2erem01")
    rt.decide = MagicMock(return_value="dec_1")
    for m in ("record_outcome", "end_run", "report_problem", "set_node"):
        setattr(rt, m, MagicMock())
    spec = NodeSpec(
        id="e2e_agent",
        name="E2E Agent",
        description="reminder e2e",
        node_type="event_loop",
        output_keys=[],  # implicit-accept on a text-only turn
        system_prompt="You are a test assistant.",
    )
    # task_capable agents carry the task tools, so TaskReminderSource's
    # applies_to gate passes (a real queen always has them).
    available = list(tools or [])
    if task_capable:
        available += [Tool(name=n, description="task tool", parameters={}) for n in TASK_WRITE_TOOLS]
    ctx = NodeContext(
        runtime=rt,
        node_id=spec.id,
        node_spec=spec,
        buffer=DataBuffer(),
        input_data={"task": "do the e2e thing"},
        llm=llm,
        available_tools=available,
        stream_id="judge",  # bypass worker auto-escalation
    )
    # The reminder sources read ctx.session_id.
    ctx.session_id = SESSION_ID
    return ctx


def _all_text(messages: Any) -> list[str]:
    """Flatten every string found anywhere in the LLM messages payload."""
    out: list[str] = []

    def walk(x: Any) -> None:
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)

    walk(messages)
    return out


@pytest.fixture
def task_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Process-singleton task store rooted at a fresh tmp dir."""
    monkeypatch.setenv("HIVE_HOME", str(tmp_path))
    import framework.tasks.store as store_mod

    monkeypatch.setattr(store_mod, "_default_store", None)
    from framework.tasks import get_task_store

    return get_task_store()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_start_reminder_reaches_the_model(task_store) -> None:
    """A resumed session with tasks → SESSION_START injects the snapshot
    as a user message the model sees on its very first turn."""
    await task_store.create_task(SESSION_ID, subject="Verify the sheet entries")
    await task_store.create_task(SESSION_ID, subject="Search X for recent posts")

    llm = MockStreamingLLM(scenarios=[_text_turn("all done")])
    ctx = _build_ctx(llm)

    result = await AgentLoop(config=LoopConfig(max_iterations=4)).execute(ctx)
    assert result.success is True

    # The model's first turn must already carry the task snapshot.
    first_turn_text = "\n".join(_all_text(llm.stream_calls[0]["messages"]))
    assert "<system-reminder>" in first_turn_text
    assert "Here are the existing tasks:" in first_turn_text
    assert "Verify the sheet entries" in first_turn_text
    assert "Search X for recent posts" in first_turn_text


@pytest.mark.asyncio
async def test_post_tool_use_reminder_rides_the_tool_result(task_store, monkeypatch: pytest.MonkeyPatch) -> None:
    """The agent creates a task mid-run; the POST_TOOL_USE point appends
    the refreshed snapshot to that tool call's result tail — so the model
    sees the new task state right where it's working."""
    # Drop the warm-up so the snapshot is due on the very first tool turn.
    import framework.tasks.reminders as rem

    monkeypatch.setattr(rem, "REMINDER_WARMUP_TURNS", 0)

    # The executor really creates the task in the store, so POST_TOOL_USE
    # observes a changed list. No tasks exist at SESSION_START.
    async def tool_exec(tu: ToolUse) -> ToolResult:
        if tu.name == "task_create":
            rec = await task_store.create_task(SESSION_ID, subject=tu.input["subject"])
            return ToolResult(tool_use_id=tu.id, content=f"Created task #{rec.id}", is_error=False)
        return ToolResult(tool_use_id=tu.id, content=f"Result for {tu.name}", is_error=False)

    llm = MockStreamingLLM(
        scenarios=[
            _tool_turn("task_create", {"subject": "Record results in the sheet"}, "call_1"),
            _text_turn("done"),
        ]
    )
    ctx = _build_ctx(llm, tools=[Tool(name="task_create", description="Create a task", parameters={})])

    result = await AgentLoop(
        tool_executor=tool_exec,
        config=LoopConfig(max_iterations=5),
    ).execute(ctx)
    assert result.success is True

    # Turn 2's input must contain the tool result with the reminder
    # appended to its tail — one message string carrying BOTH.
    turn2_texts = _all_text(llm.stream_calls[1]["messages"])
    tool_result_with_tail = [t for t in turn2_texts if "Created task #1" in t and "<system-reminder>" in t]
    assert tool_result_with_tail, "reminder was not appended to the tool result tail"
    assert "Here are the existing tasks:" in tool_result_with_tail[0]
    assert "Record results in the sheet" in tool_result_with_tail[0]


@pytest.mark.asyncio
async def test_update_only_turn_does_not_re_emit_snapshot(task_store, monkeypatch: pytest.MonkeyPatch) -> None:
    """A self-induced ``task_update`` (status flip) must NOT re-dump the
    full task list on its own POST_TOOL_USE tail — the agent just made the
    change and already saw it echoed in the tool result. The snapshot's
    "list changed" trigger is suppressed for update-only turns."""
    import framework.tasks.reminders as rem

    monkeypatch.setattr(rem, "REMINDER_WARMUP_TURNS", 0)

    rec = await task_store.create_task(SESSION_ID, subject="Record results in the sheet")

    async def tool_exec(tu: ToolUse) -> ToolResult:
        if tu.name == "task_update":
            from framework.tasks.models import TaskStatus

            await task_store.update_task(SESSION_ID, int(tu.input["id"]), status=TaskStatus.IN_PROGRESS)
            return ToolResult(tool_use_id=tu.id, content=f"Updated task #{tu.input['id']}", is_error=False)
        return ToolResult(tool_use_id=tu.id, content=f"Result for {tu.name}", is_error=False)

    llm = MockStreamingLLM(
        scenarios=[
            _tool_turn("task_update", {"id": rec.id, "status": "in_progress"}, "call_1"),
            _text_turn("done"),
        ]
    )
    ctx = _build_ctx(llm, tools=[Tool(name="task_update", description="Update a task", parameters={})])

    result = await AgentLoop(tool_executor=tool_exec, config=LoopConfig(max_iterations=5)).execute(ctx)
    assert result.success is True

    # The task_update tool result reaches turn 2 — but with NO snapshot
    # appended to its tail (the change was self-induced). The session-start
    # snapshot still lives earlier in the history; we assert specifically on
    # the update result's own message.
    turn2_texts = _all_text(llm.stream_calls[1]["messages"])
    update_result = [t for t in turn2_texts if "Updated task #1" in t]
    assert update_result, "task_update tool result not found in turn 2"
    assert all("<system-reminder>" not in t for t in update_result), "update-only turn should not re-emit the snapshot"


@pytest.mark.asyncio
async def test_counter_ticks_per_inner_turn_not_per_outer_iteration(task_store) -> None:
    """A single _run_turn_loop with N model streams advances the drift
    counter by N — proving counting tracks real turns, not the coarse
    outer judge-cycle iteration (the bug: a whole session was 1 'turn')."""

    def tool_exec(tu: ToolUse) -> ToolResult:
        return ToolResult(tool_use_id=tu.id, content="ok", is_error=False)

    # 4 tool turns + 1 text turn = 5 inner turns, all in ONE _run_turn_loop.
    llm = MockStreamingLLM(
        scenarios=[
            _tool_turn("search", {"q": "1"}, "c1"),
            _tool_turn("search", {"q": "2"}, "c2"),
            _tool_turn("search", {"q": "3"}, "c3"),
            _tool_turn("search", {"q": "4"}, "c4"),
            _text_turn("done"),
        ]
    )
    ctx = _build_ctx(llm, tools=[Tool(name="search", description="s", parameters={})])

    result = await AgentLoop(
        tool_executor=tool_exec,
        config=LoopConfig(max_iterations=5),
    ).execute(ctx)
    assert result.success is True

    from framework.tasks.store import session_storage_dir

    state_path = session_storage_dir(SESSION_ID) / "reminder_state.json"
    assert state_path.exists(), "reminder state was never persisted"
    state = json.loads(state_path.read_text())
    # 5 model streams → 5 turns. Per-outer-iteration counting (the old
    # bug) would have recorded 1.
    assert state["turns_total"] == 5
    assert state["turns_since_task_op"] == 5  # no task writes this run


@pytest.mark.asyncio
async def test_no_task_reminder_when_agent_lacks_task_tools(task_store) -> None:
    """An agent with no task tools (a bare worker) gets no task reminder
    at all — TaskReminderSource.applies_to gates it out at hub.bind(),
    so it is never observed, rendered, or persisted."""
    await task_store.create_task(SESSION_ID, subject="pre-existing work")

    def tool_exec(tu: ToolUse) -> ToolResult:
        return ToolResult(tool_use_id=tu.id, content="ok", is_error=False)

    llm = MockStreamingLLM(scenarios=[_tool_turn("search", {"q": "1"}, "c1"), _text_turn("done")])
    ctx = _build_ctx(
        llm,
        tools=[Tool(name="search", description="s", parameters={})],
        task_capable=False,  # no task tools → source must not apply
    )

    result = await AgentLoop(
        tool_executor=tool_exec,
        config=LoopConfig(max_iterations=5),
    ).execute(ctx)
    assert result.success is True

    # Nothing the model saw carries a reminder...
    all_text = "\n".join(t for c in llm.stream_calls for t in _all_text(c["messages"]))
    assert "<system-reminder>" not in all_text
    # ...and the source never even ran (render persists state; it didn't).
    from framework.tasks.store import session_storage_dir

    assert not (session_storage_dir(SESSION_ID) / "reminder_state.json").exists()
