"""Tool execution must run on a dedicated thread pool, isolated from the
default pool used by asyncio.to_thread / the HTTP server.

Regression for the swarm hang: hung browser-MCP tool calls leaked threads from
the shared default pool until it was exhausted and every API request (session
loads, colony data polls) hung forever. Tools now run on their own bounded
``hive-tool`` pool, so a tool storm can only starve other tools, never the API.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading

import pytest

import framework.agent_loop.internals.tool_result_handler as trh
from framework.agent_loop.internals.tool_result_handler import execute_tool
from framework.llm.provider import ToolResult, ToolUse


class _ToolCallEvent:
    def __init__(self, tool_name: str, tool_input: dict) -> None:
        self.tool_use_id = "test_id"
        self.tool_name = tool_name
        self.tool_input = tool_input


@pytest.mark.asyncio
async def test_tools_run_on_dedicated_hive_tool_pool() -> None:
    seen: dict = {}

    def exec_(tool_use: ToolUse) -> ToolResult:
        seen["thread"] = threading.current_thread().name
        return ToolResult(tool_use_id=tool_use.id, content="ok")

    res = await execute_tool(tool_executor=exec_, tc=_ToolCallEvent("t", {}), timeout=10)
    assert res.content == "ok"
    assert seen["thread"].startswith("hive-tool"), seen["thread"]


@pytest.mark.asyncio
async def test_hung_tools_do_not_starve_the_default_pool(monkeypatch) -> None:
    # Shrink the tool pool to 2 so we can saturate it cheaply.
    small = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="hive-tool-test")
    monkeypatch.setattr(trh, "_TOOL_EXECUTOR", small)

    release = threading.Event()

    def hung_exec(tool_use: ToolUse) -> ToolResult:
        release.wait(timeout=10)  # occupy the tool thread until released
        return ToolResult(tool_use_id=tool_use.id, content="done")

    # Fill both tool-pool threads with hung tool calls (don't await yet).
    hung = [asyncio.create_task(execute_tool(tool_executor=hung_exec, tc=_ToolCallEvent("t", {}), timeout=30)) for _ in range(2)]
    await asyncio.sleep(0.15)  # let both grab a tool thread

    # The DEFAULT pool — what the HTTP API's asyncio.to_thread reads use — must
    # remain responsive despite the tool pool being fully saturated.
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    got = await asyncio.wait_for(asyncio.to_thread(lambda: "api-ok"), timeout=2.0)
    assert got == "api-ok"
    assert loop.time() - t0 < 1.0, "default pool was blocked by hung tools"

    release.set()
    results = await asyncio.gather(*hung)
    assert all(r.content == "done" for r in results)
    small.shutdown(wait=False)
