"""Concurrency guard for the lazy tool-registry bootstrap.

The startup burst of GET /api/{queen,colony}/.../tools requests must not each
run build_queen_tool_registry_bare() — the lock in ensure_bootstrap_tool_registry
collapses that burst to a single build.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from framework.server import queen_orchestrator

pytestmark = pytest.mark.asyncio


async def test_concurrent_callers_build_registry_once(monkeypatch):
    calls = 0

    def fake_build():
        nonlocal calls
        calls += 1
        return SimpleNamespace(name=f"registry-{calls}"), {}

    monkeypatch.setattr(queen_orchestrator, "build_queen_tool_registry_bare", fake_build)

    manager = SimpleNamespace()
    results = await asyncio.gather(*(queen_orchestrator.ensure_bootstrap_tool_registry(manager) for _ in range(8)))

    assert calls == 1
    assert all(r is manager._bootstrap_tool_registry for r in results)


async def test_failed_build_is_not_cached(monkeypatch):
    attempts = 0

    def flaky_build():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("boom")
        return SimpleNamespace(name="ok"), {}

    monkeypatch.setattr(queen_orchestrator, "build_queen_tool_registry_bare", flaky_build)

    manager = SimpleNamespace()
    first = await queen_orchestrator.ensure_bootstrap_tool_registry(manager)
    assert first is None
    assert getattr(manager, "_bootstrap_tool_registry", None) is None

    second = await queen_orchestrator.ensure_bootstrap_tool_registry(manager)
    assert second is not None
    assert manager._bootstrap_tool_registry is second
