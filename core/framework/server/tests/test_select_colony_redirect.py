"""handle_select_queen_session must never adopt a colony overseer session.

Resuming a colony session without its colony binding used to materialize a
duplicate empty session dir under the queen DM tree, which
``_find_queen_session_dir``-based reads (events/history) then preferred
over the real transcript — the "blank history" bug. Select now hands the
colony binding back (``status: "colony"``) so the client routes to the
colony page, which owns the resume.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

import framework.config as hive_config
from framework.server import routes_queens, session_manager as session_manager_module
from framework.server.app import create_app
from framework.server.tests.test_api import _make_session

QUEEN = "queen_technology"
COLONY = "email_reply"
SID = "session_20260719_121546_afe89313"


def _patch_all_storage(monkeypatch, tmp_path: Path) -> Path:
    hive = tmp_path / ".hive"
    queens_dir = hive / "queens"
    colonies_dir = hive / "colonies"
    monkeypatch.setattr(routes_queens, "QUEENS_DIR", queens_dir)
    monkeypatch.setattr(session_manager_module, "QUEENS_DIR", queens_dir)
    monkeypatch.setattr(hive_config, "QUEENS_DIR", queens_dir)
    monkeypatch.setattr(session_manager_module, "COLONIES_DIR", colonies_dir)
    monkeypatch.setattr(hive_config, "COLONIES_DIR", colonies_dir)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return hive


@pytest.mark.asyncio
async def test_select_cold_colony_session_redirects_without_resuming(monkeypatch, tmp_path):
    hive = _patch_all_storage(monkeypatch, tmp_path)
    (hive / "colonies" / COLONY / "queens" / QUEEN / "sessions" / SID).mkdir(parents=True)

    app = create_app()
    manager = app["manager"]
    manager.create_session = AsyncMock()

    async with TestClient(TestServer(app)) as client:
        resp = await client.post(
            f"/api/queen/{QUEEN}/session/select",
            json={"session_id": SID},
        )
        assert resp.status == 200
        data = await resp.json()

    assert data == {
        "session_id": SID,
        "queen_id": QUEEN,
        "status": "colony",
        "colony_id": COLONY,
    }
    # The DM select must not resume the session — no DM-tree shadow dir.
    manager.create_session.assert_not_awaited()
    assert not (hive / "queens" / QUEEN / "sessions" / SID).exists()


@pytest.mark.asyncio
async def test_select_live_colony_session_redirects(monkeypatch, tmp_path):
    hive = _patch_all_storage(monkeypatch, tmp_path)
    (hive / "colonies" / COLONY / "queens" / QUEEN / "sessions" / SID).mkdir(parents=True)

    app = create_app()
    manager = app["manager"]
    live = _make_session(agent_id=SID, with_queen=False)
    live.queen_name = QUEEN
    live.colony_id = COLONY
    manager._sessions[SID] = live
    manager.create_session = AsyncMock()

    async with TestClient(TestServer(app)) as client:
        resp = await client.post(
            f"/api/queen/{QUEEN}/session/select",
            json={"session_id": SID},
        )
        assert resp.status == 200
        data = await resp.json()

    assert data == {
        "session_id": SID,
        "queen_id": QUEEN,
        "status": "colony",
        "colony_id": COLONY,
    }
    manager.create_session.assert_not_awaited()
