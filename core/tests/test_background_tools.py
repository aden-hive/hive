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
    s._injection_queue = asyncio.Queue()
    s._input_unread = False
    s._session_last_event_at = 0.0
    for name in (
        "_execute_tool",
        "_start_background_tool",
        "_collect_background_result",
        "_resolve_tool_timeout",
        "_wait_for_job",
        "_wait_budget",
        "_input_waiting",
        "_mark_session_progress",
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


def test_collect_waits_for_the_work_past_the_old_poll_limit(monkeypatch):
    monkeypatch.setattr(almod, "_queen_account_preflight", lambda tc: None)
    monkeypatch.setattr(almod, "_WAIT_TICK_S", 0.01)

    async def scenario():
        release = asyncio.Event()

        async def inner(tc, timeout):
            await release.wait()
            return ToolResult(tool_use_id=tc.tool_use_id, content="done", is_error=False)

        loop = _make_loop(inner)
        monkeypatch.setattr(loop._config, "background_tool_grace_seconds", 0)
        handle = json.loads((await loop._execute_tool(_tc("image_generate", prompt="a bee"))).content)["handle"]

        # No wait_seconds: it just waits, however long the work takes, and the idle
        # watchdog hears that the loop is alive meanwhile.
        collecting = asyncio.create_task(loop._execute_tool(_tc("collect_result", handle=handle)))
        await asyncio.sleep(0.05)
        assert not collecting.done()
        assert loop._session_last_event_at > 0
        release.set()
        assert (await collecting).content == "done"

    asyncio.run(scenario())


def test_a_new_message_ends_the_wait_and_the_work_goes_on(monkeypatch):
    monkeypatch.setattr(almod, "_queen_account_preflight", lambda tc: None)
    monkeypatch.setattr(almod, "_WAIT_TICK_S", 0.01)

    async def scenario():
        release = asyncio.Event()

        async def inner(tc, timeout):
            await release.wait()
            return ToolResult(tool_use_id=tc.tool_use_id, content="done", is_error=False)

        loop = _make_loop(inner)
        monkeypatch.setattr(loop._config, "background_tool_grace_seconds", 0)
        handle = json.loads((await loop._execute_tool(_tc("image_generate", prompt="a bee"))).content)["handle"]

        collecting = asyncio.create_task(loop._execute_tool(_tc("collect_result", handle=handle)))
        await asyncio.sleep(0.03)
        loop._injection_queue.put_nowait(("are you there?", True, None, None))
        pending = await asyncio.wait_for(collecting, timeout=1)
        assert json.loads(pending.content)["status"] == "pending"

        # A message already injected but not yet answered counts too: she hasn't read it.
        loop._injection_queue.get_nowait()
        loop._input_unread = True
        pending = await asyncio.wait_for(loop._execute_tool(_tc("collect_result", handle=handle)), timeout=1)
        assert json.loads(pending.content)["status"] == "pending"

        # The handle survives, and the work finished in the meantime.
        loop._input_unread = False
        release.set()
        assert (await loop._execute_tool(_tc("collect_result", handle=handle))).content == "done"

    asyncio.run(scenario())


def _job_logs(statuses: list[str], calls: list[dict]):
    """terminal_job_logs that reports ``statuses`` in turn, recording what it is asked."""

    async def inner(tc, timeout):
        calls.append(dict(tc.tool_input))
        status = statuses.pop(0) if len(statuses) > 1 else statuses[0]
        return ToolResult(
            tool_use_id=tc.tool_use_id,
            content=json.dumps({"status": status, "data": "" if tc.tool_input.get("max_bytes") == 0 else "the output"}),
            is_error=False,
        )

    return inner


def test_a_job_wait_stays_out_of_the_tool_call_then_reads_the_output(monkeypatch):
    monkeypatch.setattr(almod, "_queen_account_preflight", lambda tc: None)
    monkeypatch.setattr(almod, "_WAIT_TICK_S", 0.01)

    async def scenario():
        calls: list[dict] = []
        loop = _make_loop(_job_logs(["running", "running", "exited"], calls))

        result = await loop._execute_tool(_tc("terminal_job_logs", job_id="job_1", since_offset=7, wait_until_exit=True, wait_timeout_sec=30))

        assert result.tool_use_id == "call_terminal_job_logs"
        assert json.loads(result.content) == {"status": "exited", "data": "the output"}
        # Quick status checks that hold nothing open: none of them waits in the tool...
        assert calls[:-1] == [{"job_id": "job_1", "max_bytes": 0}] * 3
        # ...then the model's own read, at its offset, with nothing left to wait for.
        assert calls[-1] == {"job_id": "job_1", "since_offset": 7, "wait_until_exit": False, "wait_timeout_sec": 30}

    asyncio.run(scenario())


def test_a_job_wait_ends_at_its_timeout_or_a_new_message(monkeypatch):
    monkeypatch.setattr(almod, "_queen_account_preflight", lambda tc: None)
    monkeypatch.setattr(almod, "_WAIT_TICK_S", 0.01)

    async def scenario():
        loop = _make_loop(_job_logs(["running"], []))
        short_wait = _tc("terminal_job_logs", job_id="job_1", wait_until_exit=True, wait_timeout_sec=0.03)
        result = await asyncio.wait_for(loop._execute_tool(short_wait), timeout=1)
        assert json.loads(result.content)["status"] == "running"

        waiting = asyncio.create_task(loop._execute_tool(_tc("terminal_job_logs", job_id="job_1", wait_until_exit=True)))
        await asyncio.sleep(0.03)
        assert not waiting.done()
        loop._injection_queue.put_nowait(("are you there?", True, None, None))
        assert json.loads((await asyncio.wait_for(waiting, timeout=1)).content)["status"] == "running"

    asyncio.run(scenario())


def test_a_job_that_cant_be_found_is_reported_without_waiting(monkeypatch):
    monkeypatch.setattr(almod, "_queen_account_preflight", lambda tc: None)

    async def scenario():
        calls: list[dict] = []

        async def inner(tc, timeout):
            calls.append(dict(tc.tool_input))
            return ToolResult(tool_use_id=tc.tool_use_id, content=json.dumps({"error": "unknown job_id: job_9"}), is_error=False)

        loop = _make_loop(inner)
        result = await asyncio.wait_for(loop._execute_tool(_tc("terminal_job_logs", job_id="job_9", wait_until_exit=True)), timeout=1)

        assert "unknown job_id" in json.loads(result.content)["error"]
        assert len(calls) == 2

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
