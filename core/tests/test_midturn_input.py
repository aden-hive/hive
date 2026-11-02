"""A message that arrives while a turn is working reaches the model on its very next call.

Waits can now last minutes (collect_result, terminal_job_logs), so a message has to end the wait
and be read right after it, not one model response later.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from framework.agent_loop.agent_loop import AgentLoop, LoopConfig
from framework.agent_loop.reminders import ReminderPoint
from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolResult, ToolUse
from framework.llm.stream_events import FinishEvent, TextDeltaEvent, ToolCallEvent
from framework.orchestrator.node import DataBuffer, NodeContext, NodeSpec
from framework.tracker.decision_tracker import DecisionTracker

MESSAGE = "are you still there"


class _ScriptedLLM(LLMProvider):
    """One scripted response per stream() call, recording the messages each call was sent."""

    model = "mock"

    def __init__(self, scenarios: list[list], during_first_stream=None) -> None:
        self.scenarios = scenarios
        self.during_first_stream = during_first_stream
        self.seen: list[list[dict]] = []

    async def stream(self, messages, system="", tools=None, max_tokens=4096, **kw) -> AsyncIterator:
        self.seen.append(list(messages))
        if len(self.seen) == 1 and self.during_first_stream:
            self.during_first_stream()
        for event in self.scenarios[min(len(self.seen) - 1, len(self.scenarios) - 1)]:
            yield event

    def complete(self, messages, system="", **kw) -> LLMResponse:
        return LLMResponse(content="summary", model="mock", stop_reason="stop")


def _tool_turn(name: str, args: dict) -> list:
    return [
        ToolCallEvent(tool_use_id="c1", tool_name=name, tool_input=args),
        FinishEvent(stop_reason="tool_calls", input_tokens=10, output_tokens=5, model="mock"),
    ]


def _text_turn(text: str) -> list:
    return [
        TextDeltaEvent(content=text, snapshot=text),
        FinishEvent(stop_reason="stop", input_tokens=10, output_tokens=5, model="mock"),
    ]


def _ctx(llm: LLMProvider, tool_name: str) -> NodeContext:
    rt = MagicMock(spec=DecisionTracker)
    rt.start_run = MagicMock(return_value="session_20260101_000000_midturn01")
    rt.decide = MagicMock(return_value="dec_1")
    for method in ("record_outcome", "end_run", "report_problem", "set_node"):
        setattr(rt, method, MagicMock())
    spec = NodeSpec(id="agent", name="Agent", description="d", node_type="event_loop", output_keys=[], system_prompt="You are a test assistant.")
    ctx = NodeContext(
        runtime=rt,
        node_id=spec.id,
        node_spec=spec,
        buffer=DataBuffer(),
        input_data={"task": "start"},
        llm=llm,
        available_tools=[Tool(name=tool_name, description="a tool", parameters={"type": "object"})],
        stream_id="judge",  # bypass worker auto-escalation + reminder noise
    )
    ctx.session_id = "s_midturn"
    return ctx


@pytest.fixture(autouse=True)
def _hive_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HIVE_HOME", str(tmp_path))
    import framework.tasks.store as store_mod

    monkeypatch.setattr(store_mod, "_default_store", None)


def _position(messages: list[dict], needle: str) -> int:
    return next(i for i, m in enumerate(messages) if needle in str(m.get("content")))


@pytest.mark.asyncio
async def test_a_message_sent_while_a_tool_runs_is_read_on_the_next_call() -> None:
    loop: AgentLoop
    running = asyncio.get_running_loop()

    def tool_exec(tu: ToolUse) -> ToolResult:
        asyncio.run_coroutine_threadsafe(loop.inject_event(MESSAGE, is_client_input=True), running).result()
        return ToolResult(tool_use_id=tu.id, content="tool output", is_error=False)

    llm = _ScriptedLLM([_tool_turn("some_tool", {}), _text_turn("yes")])
    loop = AgentLoop(tool_executor=tool_exec, config=LoopConfig(max_iterations=3))

    assert (await loop.execute(_ctx(llm, "some_tool"))).success is True

    second_call = llm.seen[1]
    assert _position(second_call, "tool output") < _position(second_call, MESSAGE)


@pytest.mark.asyncio
async def test_a_message_mid_turn_gets_the_context_a_turns_first_message_gets() -> None:
    """Past conversations and the like, about that message; not left to pollute the next one's."""
    loop: AgentLoop
    running = asyncio.get_running_loop()
    fired: list[str | None] = []

    def tool_exec(tu: ToolUse) -> ToolResult:
        asyncio.run_coroutine_threadsafe(loop.inject_event(MESSAGE, is_client_input=True), running).result()
        return ToolResult(tool_use_id=tu.id, content="tool output", is_error=False)

    async def fire_reminder(point, ctx, conversation, *, user_text=None):
        if point is ReminderPoint.USER_PROMPT_SUBMIT:
            fired.append(user_text)
        return False

    llm = _ScriptedLLM([_tool_turn("some_tool", {}), _text_turn("yes")])
    loop = AgentLoop(tool_executor=tool_exec, config=LoopConfig(max_iterations=3))
    loop._fire_reminder = fire_reminder

    assert (await loop.execute(_ctx(llm, "some_tool"))).success is True

    assert fired == [MESSAGE]
    assert loop._pending_user_texts == []


@pytest.mark.asyncio
async def test_a_message_sent_during_the_response_stops_its_tool_from_waiting() -> None:
    """The model hasn't read it yet, so a wait in the response it is still writing would strand it."""
    loop: AgentLoop
    calls: list[dict] = []

    def tool_exec(tu: ToolUse) -> ToolResult:
        calls.append(dict(tu.input))
        return ToolResult(tool_use_id=tu.id, content=json.dumps({"status": "running", "data": ""}), is_error=False)

    llm = _ScriptedLLM(
        [_tool_turn("terminal_job_logs", {"job_id": "job_1", "wait_until_exit": True}), _text_turn("yes")],
        during_first_stream=lambda: loop._injection_queue.put_nowait((MESSAGE, True, None, None)),
    )
    loop = AgentLoop(tool_executor=tool_exec, config=LoopConfig(max_iterations=3, tool_wait_limit_seconds=30))

    started = time.monotonic()
    assert (await loop.execute(_ctx(llm, "terminal_job_logs"))).success is True

    assert time.monotonic() - started < 10
    assert calls == [{"job_id": "job_1", "wait_until_exit": False}]
    assert MESSAGE in str(llm.seen[1])
    # And the next response's tools may wait again: the message has been read.
    assert loop._input_unread is False
