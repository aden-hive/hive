"""Tests for DELETE /api/colonies/{colony_id} — real colony deletion.

The desktop's "Delete colony" flow drives this route. It works for both local
and pushed (VM) colonies because routing is keyed off the colony id in the URL
path — the same handler runs on whichever runtime owns the colony.

Two modes:
  - Soft (default): set metadata.json's ``deleted`` flag so the colony drops
    out of /discover while its tracked data stays on disk.
  - Purge (``?purge=true``): remove the colony's ``colonies/<id>`` and
    ``agents/<id>`` directories outright.

The handler is idempotent — deleting a colony whose dirs are already gone is a
200, which the desktop relies on when it fires the same delete at both the VM
and the local runtime.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from framework import config as framework_config
from framework.agents import discovery
from framework.host import colony_metadata
from framework.server import routes_colonies


@pytest.fixture
def hive(tmp_path, monkeypatch):
    """Point every COLONIES_DIR binding at a tmp tree.

    ``routes_colonies`` (handler), ``colony_metadata`` (soft-delete write), and
    ``framework.config`` (read live by ``discover_agents``) each resolve their
    own ``COLONIES_DIR``; all three must agree for the agents-sibling derivation
    and the discover scan to line up.
    """
    colonies = tmp_path / "colonies"
    agents = tmp_path / "agents"
    colonies.mkdir()
    agents.mkdir()
    monkeypatch.setattr(routes_colonies, "COLONIES_DIR", colonies)
    monkeypatch.setattr(colony_metadata, "COLONIES_DIR", colonies)
    monkeypatch.setattr(framework_config, "COLONIES_DIR", colonies)
    return tmp_path


def _make_colony(hive: Path, name: str, *, deleted: bool = False) -> None:
    """Create a colony's on-disk dirs. ``worker.json`` (a non-excluded JSON)
    makes the dir pass ``_is_colony_dir`` so it shows up in discovery."""
    colony_dir = hive / "colonies" / name
    colony_dir.mkdir(parents=True)
    meta: dict = {"colony_id": name, "queen_name": "tester"}
    if deleted:
        meta["deleted"] = True
    (colony_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (colony_dir / "worker.json").write_text("{}", encoding="utf-8")
    (colony_dir / "marker.txt").write_text(name, encoding="utf-8")
    agent_dir = hive / "agents" / name
    agent_dir.mkdir(parents=True)
    (agent_dir / "worker.json").write_text("{}", encoding="utf-8")


def _discover_names() -> set[str]:
    """Colony dir names currently surfaced by discovery."""
    names: set[str] = set()
    for entries in discovery.discover_agents().values():
        for e in entries:
            names.add(Path(e.path).name)
    return names


async def _client() -> TestClient:
    app = web.Application()
    routes_colonies.register_routes(app)
    return TestClient(TestServer(app))


@pytest.mark.asyncio
async def test_soft_delete_hides_from_discover_but_keeps_files(hive: Path) -> None:
    _make_colony(hive, "alpha")
    assert "alpha" in _discover_names()

    async with await _client() as c:
        resp = await c.delete("/api/colonies/alpha")
        assert resp.status == 200, await resp.text()
        body = await resp.json()

    assert body == {"deleted": "alpha", "purged": False}
    # Hidden from discovery...
    assert "alpha" not in _discover_names()
    assert colony_metadata.is_colony_soft_deleted("alpha")
    # ...but the data is still on disk in both roots.
    assert (hive / "colonies" / "alpha" / "marker.txt").read_text() == "alpha"
    assert (hive / "agents" / "alpha" / "worker.json").exists()


@pytest.mark.asyncio
async def test_purge_removes_both_dirs(hive: Path) -> None:
    _make_colony(hive, "beta")

    async with await _client() as c:
        resp = await c.delete("/api/colonies/beta?purge=true")
        assert resp.status == 200, await resp.text()
        body = await resp.json()

    assert body == {"deleted": "beta", "purged": True}
    assert not (hive / "colonies" / "beta").exists()
    assert not (hive / "agents" / "beta").exists()
    assert "beta" not in _discover_names()


@pytest.mark.asyncio
async def test_delete_missing_colony_is_idempotent(hive: Path) -> None:
    async with await _client() as c:
        soft = await c.delete("/api/colonies/ghost")
        assert soft.status == 200, await soft.text()
        assert await soft.json() == {"deleted": "ghost", "purged": False}

        purge = await c.delete("/api/colonies/ghost?purge=true")
        assert purge.status == 200, await purge.text()
        assert await purge.json() == {"deleted": "ghost", "purged": True}


@pytest.mark.asyncio
async def test_purge_only_present_dir_is_removed(hive: Path) -> None:
    # Colony dir gone (e.g. already purged elsewhere) but an agents dir lingers.
    (hive / "agents" / "gamma").mkdir(parents=True)
    (hive / "agents" / "gamma" / "worker.json").write_text("{}", encoding="utf-8")

    async with await _client() as c:
        resp = await c.delete("/api/colonies/gamma?purge=true")
        assert resp.status == 200, await resp.text()

    assert not (hive / "agents" / "gamma").exists()


@pytest.mark.asyncio
async def test_invalid_colony_id_rejected(hive: Path) -> None:
    async with await _client() as c:
        resp = await c.delete("/api/colonies/BadName")
        assert resp.status == 400, await resp.text()
