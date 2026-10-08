"""Tool-timeout policy: probe the shared MCP client before killing it.

Regression for the 2026-06-11 incident: every agent-side tool timeout
unconditionally force-disconnected the SHARED per-server MCP client,
so one slow browser_evaluate took down browser tools for every worker —
who then concluded "the browser is stuck" and pkill'd the user's Chrome.

Policy now: probe liveness first. Kill only when the server is provably
dead ("dead") or probing is unsupported ("unknown" → legacy behavior).
"alive"/"resetting" abandon the one slow call and leave the transport up.
"""

from __future__ import annotations

import time

import pytest

from framework.agent_loop.internals.tool_result_handler import execute_tool
from framework.llm.stream_events import ToolCallEvent


def _slow_executor():
    """A sync executor that outlives any test timeout."""

    def executor(tool_use):
        time.sleep(10)
        return None

    return executor


def _tc(name: str = "browser_evaluate") -> ToolCallEvent:
    return ToolCallEvent(tool_use_id="tu_1", tool_name=name, tool_input={})


@pytest.mark.asyncio
async def test_alive_server_is_not_killed():
    executor = _slow_executor()
    calls = {"probe": 0, "kill": 0}
    executor.probe_for_tool = lambda name: (calls.__setitem__("probe", calls["probe"] + 1), "alive")[1]
    executor.kill_for_tool = lambda name: calls.__setitem__("kill", calls["kill"] + 1)

    result = await execute_tool(tool_executor=executor, tc=_tc(), timeout=0.2)

    assert result.is_error
    assert "timed out after" in result.content  # telemetry needle
    assert calls["probe"] == 1
    assert calls["kill"] == 0, "alive server must NOT be force-disconnected"
    # The message must steer the agent away from the incident behavior.
    assert "DO NOT kill" in result.content
    assert "NOT an application or browser crash" in result.content


@pytest.mark.asyncio
async def test_resetting_server_is_not_killed_again():
    executor = _slow_executor()
    calls = {"kill": 0}
    executor.probe_for_tool = lambda name: "resetting"
    executor.kill_for_tool = lambda name: calls.__setitem__("kill", calls["kill"] + 1)

    result = await execute_tool(tool_executor=executor, tc=_tc(), timeout=0.2)

    assert result.is_error
    assert "timed out after" in result.content
    assert calls["kill"] == 0, "an in-flight reset must not get a second teardown stacked on it"
    assert "AUTOMATICALLY" in result.content
    assert "DO NOT kill" in result.content


@pytest.mark.asyncio
async def test_dead_server_is_killed():
    executor = _slow_executor()
    calls = {"kill": 0}
    executor.probe_for_tool = lambda name: "dead"
    executor.kill_for_tool = lambda name: calls.__setitem__("kill", calls["kill"] + 1)

    result = await execute_tool(tool_executor=executor, tc=_tc(), timeout=0.2)

    assert result.is_error
    assert "timed out after" in result.content
    assert calls["kill"] == 1, "a provably-dead server must still be torn down"
    assert "DO NOT kill" in result.content


@pytest.mark.asyncio
async def test_unknown_probe_falls_back_to_legacy_kill():
    executor = _slow_executor()
    calls = {"kill": 0}
    executor.probe_for_tool = lambda name: "unknown"
    executor.kill_for_tool = lambda name: calls.__setitem__("kill", calls["kill"] + 1)

    result = await execute_tool(tool_executor=executor, tc=_tc(), timeout=0.2)

    assert result.is_error
    assert calls["kill"] == 1


@pytest.mark.asyncio
async def test_no_probe_support_falls_back_to_legacy_kill():
    executor = _slow_executor()
    calls = {"kill": 0}
    executor.kill_for_tool = lambda name: calls.__setitem__("kill", calls["kill"] + 1)
    # no probe_for_tool attribute at all (older executors)

    result = await execute_tool(tool_executor=executor, tc=_tc(), timeout=0.2)

    assert result.is_error
    assert calls["kill"] == 1


def test_loopconfig_prefix_timeout_resolution():
    """browser_* gets the long budget; everything else keeps the default."""
    from framework.agent_loop.agent_loop import AgentLoop
    from framework.agent_loop.internals.types import LoopConfig

    class _Stub:
        _config = LoopConfig()

    stub = _Stub()
    resolve = AgentLoop._resolve_tool_timeout

    assert resolve(stub, "browser_evaluate") == 180.0
    assert resolve(stub, "browser_status") == 180.0
    assert resolve(stub, "terminal_exec") == 60.0
    assert resolve(stub, "tracker_query") == 60.0

    # Longest prefix wins; empty overrides fall back cleanly.
    stub._config = LoopConfig(tool_timeout_overrides={"browser_": 180.0, "browser_evaluate": 300.0})
    assert resolve(stub, "browser_evaluate") == 300.0
    assert resolve(stub, "browser_open") == 180.0
    stub._config = LoopConfig(tool_timeout_overrides={})
    assert resolve(stub, "browser_evaluate") == 60.0

    # INVARIANT: agent-side budgets stay below the MCP call-result ceiling.
    from framework.loader.mcp_client import MCPClient

    cfg = LoopConfig()
    ceiling = MCPClient._CALL_RESULT_TIMEOUT
    assert cfg.tool_call_timeout_seconds < ceiling
    assert all(v < ceiling for v in cfg.tool_timeout_overrides.values())
