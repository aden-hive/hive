"""Shared fixtures for dummy agent end-to-end tests.

These tests use real LLM providers — they are NOT part of regular CI.
Run via: cd core && uv run python tests/dummy_agents/run_all.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from framework.graph.executor import GraphExecutor, ParallelExecutionConfig
from framework.graph.goal import Goal
from framework.llm.litellm import LiteLLMProvider
from framework.runtime.core import Runtime

# ── module-level state set by run_all.py ─────────────────────────────

_selected_model: str | None = None
_selected_api_key: str | None = None
_selected_extra_headers: dict[str, str] | None = None
_selected_api_base: str | None = None
_EXECUTION_TIMEOUT_SECS = float(os.environ.get("DUMMY_AGENT_EXEC_TIMEOUT_SECS", "90"))


def set_llm_selection(
    model: str,
    api_key: str,
    extra_headers: dict[str, str] | None = None,
    api_base: str | None = None,
) -> None:
    """Called by run_all.py after user selects a provider."""
    global _selected_model, _selected_api_key, _selected_extra_headers, _selected_api_base
    _selected_model = model
    _selected_api_key = api_key
    _selected_extra_headers = extra_headers
    _selected_api_base = api_base


# ── collection hook: skip entire directory when not configured ───────


def pytest_collection_modifyitems(config, items):
    """Skip all dummy_agents tests when no LLM is configured.

    This prevents these tests from running in regular CI. They only run
    when launched via run_all.py (which calls set_llm_selection first).
    """
    if _selected_model is not None:
        return  # LLM configured, run normally

    skip = pytest.mark.skip(
        reason="Dummy agent tests require a real LLM. "
        "Run via: cd core && uv run python tests/dummy_agents/run_all.py"
    )
    for item in items:
        if "dummy_agents" in str(item.fspath):
            item.add_marker(skip)


# ── fixtures ─────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def llm_provider():
    """Real LLM provider using the user-selected model."""
    if _selected_model is None or _selected_api_key is None:
        pytest.skip("No LLM selected — run via run_all.py")
    kwargs = {"model": _selected_model, "api_key": _selected_api_key}
    if _selected_extra_headers:
        kwargs["extra_headers"] = _selected_extra_headers
    if _selected_api_base:
        kwargs["api_base"] = _selected_api_base
    return LiteLLMProvider(**kwargs)


@pytest.fixture(scope="session")
def tool_registry():
    """Load hive-tools MCP server and return a ToolRegistry with real tools.

    Session-scoped so the MCP server is started once and reused across tests.
    """
    from framework.runner.tool_registry import ToolRegistry

    registry = ToolRegistry()
    # Resolve the tools directory relative to the repo root
    repo_root = Path(__file__).resolve().parents[3]  # core/tests/dummy_agents -> repo root
    tools_dir = repo_root / "tools"

    mcp_config = {
        "name": "hive-tools",
        "transport": "stdio",
        "command": "uv",
        "args": ["run", "python", "mcp_server.py", "--stdio"],
        "cwd": str(tools_dir),
        "description": "Hive tools MCP server",
    }
    registry.register_mcp_server(mcp_config)
    yield registry
    registry.cleanup()


@pytest.fixture
def runtime(tmp_path):
    """Real Runtime backed by a temp directory."""
    return Runtime(storage_path=tmp_path / "runtime")


@pytest.fixture
def goal():
    return Goal(id="dummy", name="Dummy Agent Test", description="Level 2 end-to-end testing")


def make_executor(
    runtime: Runtime,
    llm: LiteLLMProvider,
    *,
    enable_parallel: bool = True,
    parallel_config: ParallelExecutionConfig | None = None,
    loop_config: dict | None = None,
    tool_registry=None,
    storage_path: Path | None = None,
) -> GraphExecutor:
    """Factory that creates a GraphExecutor with a real LLM."""
    tools = []
    tool_executor = None
    if tool_registry is not None:
        tools = list(tool_registry.get_tools().values())
        tool_executor = tool_registry.get_executor()

    executor = GraphExecutor(
        runtime=runtime,
        llm=llm,
        tools=tools,
        tool_executor=tool_executor,
        enable_parallel_execution=enable_parallel,
        parallel_config=parallel_config,
        loop_config=loop_config or {"max_iterations": 10},
        storage_path=storage_path,
    )

    original_execute = executor.execute

    async def execute_with_timeout(*args, **kwargs):
        try:
            return await asyncio.wait_for(
                original_execute(*args, **kwargs),
                timeout=_EXECUTION_TIMEOUT_SECS,
            )
        except TimeoutError as e:
            raise TimeoutError(
                "Dummy agent execution timed out after "
                f"{_EXECUTION_TIMEOUT_SECS:.0f}s. "
                "This usually means the current worker execution path "
                "(GraphExecutor -> WorkerAgent -> EventLoopNode) is stuck "
                "waiting on the provider or tool-calling behavior."
            ) from e

    executor.execute = execute_with_timeout  # type: ignore[method-assign]
    return executor
