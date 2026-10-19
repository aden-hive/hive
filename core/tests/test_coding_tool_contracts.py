"""Public tool contracts across discovery, execution and role configuration."""

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest
from fastmcp import FastMCP

from framework.agent_loop.agent_loop import AgentLoop
from framework.agent_loop.internals.types import LoopConfig
from framework.agents.queen.queen_tools_defaults import _TOOL_CATEGORIES, always_enabled_tool_names
from framework.llm.provider import Tool, ToolResult
from framework.llm.stream_events import ToolCallEvent
from framework.tools.queen_lifecycle_tools import QueenPhaseState
from framework.tools.tool_tiers import ToolTierState, build_search_tools


def _tool(name):
    return Tool(name=name, description=name, parameters={"type": "object"})


@pytest.mark.parametrize("role", ["queen", "worker"])
def test_inventory_reports_configuration_without_loading(role):
    pool = [_tool(name) for name in ("attach_file", "web_search", "edit_file")]
    registered = {t.name for t in pool}
    allowed = ["attach_file", "web_search", "chart_render"]
    if role == "queen":
        state = QueenPhaseState(
            independent_tools=pool, mcp_tool_names_all=registered, enabled_mcp_tools=allowed, always_enabled_names={"attach_file"}
        )
    else:
        state = ToolTierState(pool=pool, gateable_names=registered, enabled_allowlist=allowed, always_enabled_names={"attach_file"})
    _, search = build_search_tools(state)
    inventory = json.loads(asyncio.run(search(query="inventory")))
    assert inventory["loaded"] == ["attach_file"]
    assert inventory["searchable"] == ["web_search"]
    assert inventory["disabled"] == ["edit_file"]
    assert inventory["unavailable"] == ["chart_render"]
    assert not state.loaded_tool_names
    assert "does not verify" in inventory["note"]
    result = json.loads(asyncio.run(search(query="select:web_search")))
    assert result["loaded"] == ["web_search"]
    inventory = json.loads(asyncio.run(search(query="inventory")))
    assert inventory["loaded"] == ["attach_file", "web_search"]
    assert inventory["searchable"] == []


def _call(name, **inputs):
    return ToolCallEvent(tool_use_id="test_" + name, tool_name=name, tool_input=inputs)


def _loop(inner):
    loop = SimpleNamespace(_config=LoopConfig(), _bg_counter=0, _background_calls={}, _execute_tool_inner=inner)
    for name in ("_execute_tool", "_start_background_tool", "_collect_background_result", "_resolve_tool_timeout"):
        setattr(loop, name, getattr(AgentLoop, name).__get__(loop))
    return loop


def test_default_tools_retrieve_nested_background_result(monkeypatch):
    from terminal_tools.common.limits import ShellSpec
    from terminal_tools.exec import register_exec_tools
    from terminal_tools.jobs.manager import JobManager
    from terminal_tools.jobs.tools import register_job_tools

    manager = JobManager()
    monkeypatch.setattr("terminal_tools.jobs.manager._MANAGER", manager)
    monkeypatch.setattr("terminal_tools.exec.resolve_shell_spec", lambda _: ShellSpec(sys.executable, ("-c",), "direct"))
    monkeypatch.setattr("framework.agent_loop.agent_loop._queen_account_preflight", lambda _: None)
    mcp = FastMCP("nested-background-test")
    register_exec_tools(mcp)
    register_job_tools(mcp)
    allowed = always_enabled_tool_names()

    async def inner(call, timeout):
        assert call.tool_name in allowed
        fn = mcp._tool_manager._tools[call.tool_name].fn
        result = await asyncio.to_thread(fn, **call.tool_input)
        return ToolResult(tool_use_id=call.tool_use_id, content=json.dumps(result), is_error=False)

    async def scenario():
        loop = _loop(inner)
        loop._config.background_tool_grace_seconds = 0.01
        started = json.loads(
            (
                await loop._execute_tool(
                    _call(
                        "terminal_exec",
                        command="import time; time.sleep(0.5); print('finished')",
                        shell=True,
                        timeout_sec=3,
                        auto_background_after_sec=0.1,
                    )
                )
            ).content
        )
        result = json.loads((await loop._execute_tool(_call("collect_result", handle=started["handle"], wait_seconds=5))).content)
        assert result["auto_backgrounded"]
        final = json.loads((await loop._execute_tool(_call("terminal_job_logs", job_id=result["job_id"], wait_until_exit=True))).content)
        assert final["status"] == "exited"
        assert final["exit_code"] == 0
        assert final["data"].strip() == "finished"

    try:
        asyncio.run(scenario())
    finally:
        manager.shutdown_all(grace_sec=0)


def test_shorter_caller_budget_rejects_uncollectable_foreground_wait():
    async def inner(call, timeout):
        pytest.fail("invalid wait reached the tool executor")

    loop = _loop(inner)
    loop._config.background_tool_timeout_seconds = 10
    result = asyncio.run(loop._start_background_tool(_call("terminal_exec", timeout_sec=60, auto_background_after_sec=0)))
    assert result.is_error
    assert "auto_background_after_sec" in result.content
    assert not loop._background_calls


def test_code_editing_includes_the_required_read_tool():
    from framework.agents.queen.queen_profiles import DEFAULT_QUEENS

    assert "code_editing" in DEFAULT_QUEENS["queen_technology"]["default_tool_categories"]
    assert set(_TOOL_CATEGORIES["code_editing"]) == {"read_file", "edit_file"}
