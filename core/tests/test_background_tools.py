"""Tests for the generic background-tool mechanism in the agent-loop caller.

A tool in ``LoopConfig.background_tools`` (e.g. image_generate) returns a handle
immediately and runs to completion off the agent's critical path; the agent
retrieves it via the synthetic ``collect_result`` tool. We exercise the three
``AgentLoop`` helpers directly by binding them onto a lightweight object so we
don't need to construct a full loop.
"""

from __future__ import annotations

import asyncio
import json
import types as pytypes

import framework.agent_loop.agent_loop as almod
from framework.agent_loop.agent_loop import AgentLoop
from framework.agent_loop.internals.synthetic_tools import build_collect_result_tool
from framework.agent_loop.internals.types import LoopConfig
from framework.llm.provider import Tool, ToolResult
from framework.llm.stream_events import ToolCallEvent


def _make_loop(inner):
    """A minimal stand-in with the background helpers bound to it."""
    s = pytypes.SimpleNamespace()
    s._config = LoopConfig()  # background_tools defaults to {"image_generate"}
    s._bg_counter = 0
    s._background_calls = {}
    s._execute_tool_inner = inner
    for name in (
        "_execute_tool",
        "_start_background_tool",
        "_collect_background_result",
        "_resolve_tool_timeout",
    ):
        setattr(s, name, getattr(AgentLoop, name).__get__(s))
    return s


def _tc(tool_name: str, **inp) -> ToolCallEvent:
    return ToolCallEvent(tool_use_id=f"call_{tool_name}", tool_name=tool_name, tool_input=inp)


def test_background_dispatch_then_collect(monkeypatch):
    monkeypatch.setattr(almod, "_queen_account_preflight", lambda tc: None)

    async def scenario():
        release = asyncio.Event()

        async def inner(tc, timeout):
            # Mimic the real image_generate result shape; block until released.
            await release.wait()
            return ToolResult(
                tool_use_id=tc.tool_use_id,
                content=json.dumps({"images": [{"path": "/x/img.png"}], "usage": {"credits": 8.5}}),
                is_error=False,
            )

        loop = _make_loop(inner)

        # 1. A background tool returns a handle immediately and is registered.
        started = await loop._execute_tool(_tc("image_generate", prompt="a bee"))
        sp = json.loads(started.content)
        assert sp["status"] == "started"
        handle = sp["handle"]
        assert handle in loop._background_calls

        # 2. collect_result while the work is still running → pending.
        pending = await loop._execute_tool(_tc("collect_result", handle=handle, wait_seconds=1))
        assert json.loads(pending.content)["status"] == "pending"
        assert handle in loop._background_calls  # not consumed on pending

        # 3. Release the work; collect_result now returns the REAL result,
        #    re-attached to the collect call's id, and pops the entry.
        release.set()
        done = await loop._execute_tool(_tc("collect_result", handle=handle, wait_seconds=5))
        dp = json.loads(done.content)
        assert dp["images"][0]["path"] == "/x/img.png"
        assert dp["usage"]["credits"] == 8.5
        assert done.tool_use_id == "call_collect_result"
        assert handle not in loop._background_calls

        # 4. Unknown / already-collected handle → error (not a crash).
        err = await loop._execute_tool(_tc("collect_result", handle="bg_999"))
        assert err.is_error
        assert "Unknown" in json.loads(err.content)["error"]

    asyncio.run(scenario())


def test_dynamic_refresh_preserves_collect_result():
    """The queen rebuilds its tool list each turn from the dynamic provider;
    collect_result is a framework synthetic that must survive that refresh (it
    is not sourced from the provider). Regression for it being dropped — which
    left the agent unable to retrieve a backgrounded result."""
    s = pytypes.SimpleNamespace()
    s._DYNAMIC_REFRESH_SYNTHETIC_NAMES = AgentLoop._DYNAMIC_REFRESH_SYNTHETIC_NAMES
    s._refresh_dynamic_tools = AgentLoop._refresh_dynamic_tools.__get__(s)

    collect = build_collect_result_tool()
    image = Tool(name="image_generate", description="d", parameters={"type": "object"})
    ctx = pytypes.SimpleNamespace(dynamic_tools_provider=lambda: [image])
    # Initial list (as built once at loop start) carries the synthetic.
    tools = [image, collect]
    s._refresh_dynamic_tools(ctx, tools)
    names = [t.name for t in tools]
    assert "collect_result" in names, "collect_result must survive the per-turn dynamic refresh"
    assert "image_generate" in names


def test_non_background_tool_runs_inline(monkeypatch):
    monkeypatch.setattr(almod, "_queen_account_preflight", lambda tc: None)

    async def scenario():
        calls: list[str] = []

        async def inner(tc, timeout):
            calls.append(tc.tool_name)
            return ToolResult(tool_use_id=tc.tool_use_id, content="ok", is_error=False)

        loop = _make_loop(inner)
        res = await loop._execute_tool(_tc("terminal_exec", command="ls"))
        # Ran inline (not backgrounded): no handle, inner was invoked directly.
        assert res.content == "ok"
        assert calls == ["terminal_exec"]
        assert loop._background_calls == {}

    asyncio.run(scenario())
