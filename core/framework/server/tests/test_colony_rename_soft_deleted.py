"""Tests for renaming/creating onto a soft-deleted colony's name.

A soft-deleted colony keeps its ``colonies/<id>`` and ``agents/<id>`` dirs on
disk (only metadata.json's ``deleted`` flag is set) but is invisible and
unrecoverable to the user. Before the fix, that leftover directory squatted on
the name: a rename or create targeting it failed with a confusing "already
exists" — or silently resurrected the dead colony. The handlers now park the
dead colony aside (via ``vacate_soft_deleted_colony``) so the name is reusable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from framework.host import colony_metadata
from framework.server import routes_colonies


@pytest.fixture
def hive(tmp_path, monkeypatch):
    """Redirect COLONIES_DIR (and the sibling agents dir) into a tmp tree.

    Both ``routes_colonies`` and ``colony_metadata`` read their own
    module-level ``COLONIES_DIR``; the rename handler delegates the
    soft-deleted check to ``colony_metadata``, so both must point at the
    same tmp colonies dir for the agents-sibling derivation to line up.
    """
    colonies = tmp_path / "colonies"
    agents = tmp_path / "agents"
    colonies.mkdir()
    agents.mkdir()
    monkeypatch.setattr(routes_colonies, "COLONIES_DIR", colonies)
    monkeypatch.setattr(colony_metadata, "COLONIES_DIR", colonies)
    return tmp_path


def _make_colony(hive: Path, name: str, *, deleted: bool = False) -> None:
    """Create a colony's on-disk dirs with a metadata.json + an agent dir."""
    colony_dir = hive / "colonies" / name
    colony_dir.mkdir(parents=True)
    meta: dict = {"colony_id": name}
    if deleted:
        meta["deleted"] = True
    (colony_dir / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    (colony_dir / "marker.txt").write_text(name, encoding="utf-8")
    agent_dir = hive / "agents" / name
    agent_dir.mkdir(parents=True)
    (agent_dir / "worker.json").write_text("{}", encoding="utf-8")


async def _client() -> TestClient:
    app = web.Application()
    routes_colonies.register_routes(app)
    return TestClient(TestServer(app))


# ── vacate_soft_deleted_colony ─────────────────────────────────────────────


def test_vacate_parks_soft_deleted_colony(hive: Path) -> None:
    _make_colony(hive, "ghost", deleted=True)

    parked = colony_metadata.vacate_soft_deleted_colony("ghost")

    assert parked == "ghost.deleted.1"
    # Name is free in both roots now...
    assert not (hive / "colonies" / "ghost").exists()
    assert not (hive / "agents" / "ghost").exists()
    # ...and the data was preserved under the parked name, not destroyed.
    assert (hive / "colonies" / "ghost.deleted.1" / "marker.txt").read_text() == "ghost"
    assert (hive / "agents" / "ghost.deleted.1" / "worker.json").exists()


def test_vacate_is_noop_for_live_colony(hive: Path) -> None:
    _make_colony(hive, "alive", deleted=False)

    assert colony_metadata.vacate_soft_deleted_colony("alive") is None
    assert (hive / "colonies" / "alive").exists()
    assert (hive / "agents" / "alive").exists()


def test_vacate_is_noop_for_missing_colony(hive: Path) -> None:
    assert colony_metadata.vacate_soft_deleted_colony("nope") is None


def test_vacate_picks_next_free_suffix(hive: Path) -> None:
    _make_colony(hive, "ghost", deleted=True)
    # A prior park already used .deleted.1 in the colonies root.
    (hive / "colonies" / "ghost.deleted.1").mkdir()

    assert colony_metadata.vacate_soft_deleted_colony("ghost") == "ghost.deleted.2"


# ── rename handler ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rename_onto_soft_deleted_name_succeeds(hive: Path) -> None:
    _make_colony(hive, "keep", deleted=False)
    _make_colony(hive, "taken", deleted=True)

    async with await _client() as c:
        resp = await c.post("/api/colonies/keep/rename", json={"new_name": "taken"})
        assert resp.status == 200, await resp.text()
        body = await resp.json()

    assert body == {"renamed": True, "old_name": "keep", "new_name": "taken"}
    # The live colony now occupies the freed name, with its data intact.
    assert (hive / "colonies" / "taken" / "marker.txt").read_text() == "keep"
    assert (hive / "agents" / "taken" / "worker.json").exists()
    assert not (hive / "colonies" / "keep").exists()
    # The dead colony was preserved aside, not clobbered.
    assert (hive / "colonies" / "taken.deleted.1" / "marker.txt").read_text() == "taken"


@pytest.mark.asyncio
async def test_rename_onto_live_name_still_conflicts(hive: Path) -> None:
    _make_colony(hive, "keep", deleted=False)
    _make_colony(hive, "live", deleted=False)

    async with await _client() as c:
        resp = await c.post("/api/colonies/keep/rename", json={"new_name": "live"})
        assert resp.status == 409, await resp.text()

    # Both colonies untouched.
    assert (hive / "colonies" / "keep").exists()
    assert (hive / "colonies" / "live" / "marker.txt").read_text() == "live"
