"""Shared fixtures for dummy agent end-to-end tests.

These tests use real LLM providers — they are NOT part of regular CI.
Run via: cd core && uv run python tests/dummy_agents/run_all.py
"""

from __future__ import annotations

import asyncio
import json
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


def _try_auto_configure_from_hive_config() -> bool:
    """Try to load LLM provider from ~/.hive/configuration.json.

    Returns True if successfully configured, False otherwise.
    """
    try:
        from framework.config import (
            get_api_base,
            get_api_key,
            get_llm_extra_kwargs,
            get_preferred_model,
        )

        model = get_preferred_model()
        api_key = get_api_key()
        if not model or not api_key:
            return False

        extra_kwargs = get_llm_extra_kwargs()
        set_llm_selection(
            model=model,
            api_key=api_key,
            api_base=get_api_base(),
            extra_headers=extra_kwargs.get("extra_headers"),
        )
        return True
    except Exception:
        return False


def pytest_collection_modifyitems(config, items):
    """Skip all dummy_agents tests when no LLM is configured.

    Resolution order:
    1. Already configured via run_all.py (set_llm_selection called)
    2. Auto-configure from ~/.hive/configuration.json
    3. Skip tests
    """
    if _selected_model is not None:
        return  # LLM configured via run_all.py, run normally

    # Try auto-configure from hive config
    if _try_auto_configure_from_hive_config():
        return  # Config found, run tests

    skip = pytest.mark.skip(
        reason="Dummy agent tests require a real LLM. "
        "Configure ~/.hive/configuration.json or "
        "run via: cd core && uv run python tests/dummy_agents/run_all.py"
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
    event_bus=None,
    stream_id: str = "",
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
        event_bus=event_bus,
        stream_id=stream_id,
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


# ── Artifact capture: raw output written to disk for every test ──────

ARTIFACTS_DIR = Path("/tmp/hive_test_artifacts")


class TestArtifact:
    """Collects raw output + expected behavior for a single test.

    Captures TWO kinds of data:
    1. Checks: individual assertion results (expected vs actual)
    2. Framework raw output: the real conversation, state, tool calls
       written by the executor to storage_path — copied verbatim,
       not curated.

    Usage in tests:
        def test_foo(artifact, ...):
            result = await executor.execute(...)
            artifact.record(result, expected="...", storage_path=tmp_path/"session")
    """

    def __init__(self, test_id: str):
        self.test_id = test_id
        self._safe_name = test_id.replace("::", "__").replace("/", "_")
        self._dir = ARTIFACTS_DIR / self._safe_name
        self._data: dict = {"test_id": test_id, "raw_output": None, "expected": "", "checks": []}

    def record(self, result, *, expected: str = "", storage_path=None):
        """Record an ExecutionResult and copy real framework files."""
        self._data["expected"] = expected
        if result is None:
            self._data["raw_output"] = None
            return
        self._data["raw_output"] = {
            "success": getattr(result, "success", None),
            "output": _safe_serialize(getattr(result, "output", {})),
            "error": getattr(result, "error", None),
            "path": getattr(result, "path", []),
            "steps_executed": getattr(result, "steps_executed", 0),
            "total_tokens": getattr(result, "total_tokens", 0),
            "total_latency_ms": getattr(result, "total_latency_ms", 0),
            "execution_quality": getattr(result, "execution_quality", ""),
            "total_retries": getattr(result, "total_retries", 0),
            "node_visit_counts": getattr(result, "node_visit_counts", {}),
            "nodes_with_failures": getattr(result, "nodes_with_failures", []),
            "session_state_buffer": _safe_serialize(
                (getattr(result, "session_state", {}) or {}).get("data_buffer", {})
            ),
        }
        # Copy real framework output files (conversations, state, runs)
        if storage_path is not None:
            self._copy_framework_files(Path(storage_path))

    def _copy_framework_files(self, storage_path: Path):
        """Copy real framework output to persistent artifact directory."""
        import shutil

        raw_dir = self._dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        if storage_path.exists():
            for src in storage_path.rglob("*"):
                if src.is_file() and src.suffix in (".json", ".jsonl", ".txt"):
                    rel = src.relative_to(storage_path)
                    dst = raw_dir / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)

    def record_value(self, key: str, value, *, expected: str = ""):
        """Record an arbitrary key-value (for non-ExecutionResult tests)."""
        self._data.setdefault("values", {})[key] = _safe_serialize(value)
        if expected:
            self._data["expected"] = expected

    def check(self, description: str, passed: bool, actual: str = "", expected_val: str = ""):
        """Record an individual assertion check."""
        self._data["checks"].append(
            {
                "description": description,
                "passed": passed,
                "actual": actual,
                "expected": expected_val,
            }
        )

    def save(self):
        """Write artifact to disk."""
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / "artifact.json"
        with open(path, "w") as f:
            json.dump(self._data, f, indent=2, default=str)


def _safe_serialize(obj):
    """Convert to JSON-safe types."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_serialize(v) for v in obj]
    return str(obj)[:500]


@pytest.fixture
def artifact(request, tmp_path):
    """Fixture that captures raw test output to disk.

    Every test gets an artifact recorder. Call artifact.record(result)
    and artifact.check("description", passed, actual, expected) to
    capture data. Saved automatically on teardown.

    On teardown, copies ALL framework output files (conversations, state,
    tool logs) from tmp_path to the persistent artifact directory. This
    captures the REAL raw output — not curated summaries.
    """
    test_id = request.node.nodeid
    art = TestArtifact(test_id)
    yield art
    # Copy all framework files from the test's tmp_path
    art._copy_framework_files(tmp_path)
    art.save()


# Autouse hook: for tests that DON'T use the artifact fixture,
# create a minimal artifact from pass/fail status.
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when == "call":
        item._test_report = rep


def pytest_runtest_teardown(item, nextitem):
    """Auto-save a minimal artifact for tests that didn't use the fixture."""
    report = getattr(item, "_test_report", None)
    if report is None:
        return
    # Check if the test already used the artifact fixture
    if "artifact" in item.fixturenames:
        return  # Already handled by fixture teardown
    safe_name = item.nodeid.replace("::", "__").replace("/", "_")
    out_dir = ARTIFACTS_DIR / safe_name
    out_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "test_id": item.nodeid,
        "raw_output": None,
        "expected": "",
        "checks": [],
        "auto_captured": True,
        "status": "PASS" if report.passed else ("FAIL" if report.failed else "SKIP"),
    }
    if report.failed and report.longreprtext:
        data["failure_text"] = report.longreprtext[:5000]
    with open(out_dir / "artifact.json", "w") as f:
        json.dump(data, f, indent=2, default=str)
