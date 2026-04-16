"""Regression test for contextvars propagation through tool executor threads.

When execute_tool offloads a sync tool executor to a thread pool via
run_in_executor, Python does not automatically propagate contextvars.
This caused auto-injected params like data_dir to be lost, making MCP
tools (save_data, serve_file_to_user, etc.) fail with
"Missing required argument: data_dir".

Fix: wrap the executor call in contextvars.copy_context().run().
"""

from __future__ import annotations

import pytest

from framework.agent_loop.internals.tool_result_handler import execute_tool
from framework.llm.provider import ToolResult, ToolUse
from framework.loader.tool_registry import _execution_context


class _ToolCallEvent:
    """Minimal stand-in for ToolCallEvent used by execute_tool."""

    def __init__(self, tool_name: str, tool_input: dict) -> None:
        self.tool_use_id = "test_id"
        self.tool_name = tool_name
        self.tool_input = tool_input


@pytest.mark.asyncio
async def test_execution_context_propagates_to_tool_executor() -> None:
    """data_dir set via set_execution_context must be visible inside
    the tool executor even though it runs in a thread pool."""

    captured: dict = {}

    def capturing_executor(tool_use: ToolUse) -> ToolResult:
        # This runs inside run_in_executor (a worker thread).
        # Before the fix, _execution_context.get() returned None here.
        ctx = _execution_context.get()
        captured["exec_ctx"] = ctx
        return ToolResult(
            tool_use_id=tool_use.id,
            content="ok",
        )

    token = _execution_context.set({"data_dir": "/tmp/test_data"})
    try:
        tc = _ToolCallEvent("test_tool", {"arg": "value"})
        result = await execute_tool(
            tool_executor=capturing_executor,
            tc=tc,
            timeout=10,
        )
    finally:
        _execution_context.reset(token)

    assert result.content == "ok"
    assert captured["exec_ctx"] is not None, (
        "execution context was None inside worker thread, contextvars did not propagate through run_in_executor"
    )
    assert captured["exec_ctx"]["data_dir"] == "/tmp/test_data"


@pytest.mark.asyncio
async def test_execution_context_none_when_not_set() -> None:
    """When no execution context is set, executor should still work
    (context is None, not an error)."""

    captured: dict = {}

    def capturing_executor(tool_use: ToolUse) -> ToolResult:
        captured["exec_ctx"] = _execution_context.get()
        return ToolResult(
            tool_use_id=tool_use.id,
            content="ok",
        )

    # Don't set any execution context
    tc = _ToolCallEvent("test_tool", {})
    result = await execute_tool(
        tool_executor=capturing_executor,
        tc=tc,
        timeout=10,
    )

    assert result.content == "ok"
    assert captured["exec_ctx"] is None
