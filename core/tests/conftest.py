"""Test setup for framework tests.

Two responsibilities:

1. **MCP submodule bindings** -- ensures ``framework.loader`` submodules
   are attached to the parent package so monkeypatch's dotted-string API
   (``monkeypatch.setattr("framework.loader.foo.Y", ...)``) resolves even
   when no test has imported the submodule yet.

2. **Global hive-home isolation** -- redirects ``~/.hive`` to a per-test
   tmp directory for every test in the suite. Without this, any test
   that instantiates a real ``SessionManager`` or calls ``_start_queen``
   leaks real session directories into the developer's actual
   ``~/.hive/agents/queens/`` tree, polluting the queen DM history and
   occasionally hijacking the live server's navigation.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import framework.loader  # noqa: F401 — load parent package first
import framework.loader.mcp_client as _mcp_client
import framework.loader.mcp_connection_manager as _mcp_connection_manager
import framework.loader.mcp_registry as _mcp_registry

framework.loader.mcp_registry = _mcp_registry
framework.loader.mcp_connection_manager = _mcp_connection_manager
framework.loader.mcp_client = _mcp_client


# ---------------------------------------------------------------------------
# Global hive-home isolation
# ---------------------------------------------------------------------------


_HIVE_PATH_CONSUMERS = (
    "framework.config",
    "framework.server.session_manager",
    "framework.server.queen_orchestrator",
    "framework.server.routes_queens",
    "framework.server.routes_skills",
    "framework.server.app",
    "framework.agents.discovery",
    "framework.agents.queen.queen_profiles",
    "framework.tools.queen_lifecycle_tools",
    "framework.storage.migrate_v2",
    "framework.loader.cli",
)

_HIVE_PATH_NAMES = (
    ("HIVE_HOME", lambda h: h),
    ("QUEENS_DIR", lambda h: h / "agents" / "queens"),
    ("COLONIES_DIR", lambda h: h / "colonies"),
    ("MEMORIES_DIR", lambda h: h / "memories"),
    ("HIVE_CONFIG_FILE", lambda h: h / "configuration.json"),
)


@pytest.fixture(autouse=True)
def _isolate_hive_home_autouse(tmp_path, monkeypatch):
    """Per-test isolation of ``~/.hive`` to ``tmp_path/.hive``.

    Every test automatically gets Path.home() redirected to its own
    tmp directory and every module-level ``HIVE_HOME``/``QUEENS_DIR``/
    ``COLONIES_DIR`` binding rewritten. Tests that need to read from
    the developer's real home can explicitly unpatch these by calling
    ``monkeypatch.undo()`` at the start -- none currently do.
    """
    fake_home_root = tmp_path
    fake_hive = fake_home_root / ".hive"
    fake_hive.mkdir(exist_ok=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home_root))
    for mod_name in _HIVE_PATH_CONSUMERS:
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue
        for attr_name, builder in _HIVE_PATH_NAMES:
            if hasattr(mod, attr_name):
                monkeypatch.setattr(mod, attr_name, builder(fake_hive))
    yield fake_hive
