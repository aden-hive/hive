"""E2E coverage for task_create(new_session=true) session supersession.

Exercises the real HTTP handlers + a real SessionManager against
on-disk queen session directories. The fork itself (compaction) needs a
live LLM and is not covered here; these tests pin the deterministic
retirement / resolution behavior around it:

  * handle_select_queen_session follows the superseded_by chain
  * handle_queen_session skips a retired session on cold-resume
  * /chat locks a superseded session
  * /chat re-arms a freshly-forked session (clears fork_kickoff_pending)
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

import framework.config as hive_config
from framework.server import routes_queens, session_manager as session_manager_module
from framework.server.app import create_app
from framework.server.tests.test_api import _make_session, _write_queen_session

QUEEN = "queen_technology"


def _patch_all_queen_storage(monkeypatch, tmp_path: Path) -> Path:
    """Point every queen-storage resolver at the test hive home."""
    queens_dir = tmp_path / ".hive" / "queens"
    monkeypatch.setattr(routes_queens, "QUEENS_DIR", queens_dir)
    monkeypatch.setattr(session_manager_module, "QUEENS_DIR", queens_dir)
    monkeypatch.setattr(hive_config, "QUEENS_DIR", queens_dir)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return queens_dir


# ---------------------------------------------------------------------------
# handle_select_queen_session — chain following
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_follows_supersession_chain_to_cold_successor(monkeypatch, tmp_path):
    """Selecting a retired session (A) resolves forward through B to the
    live-able tail C — never re-animating a stopped ancestor."""
    _patch_all_queen_storage(monkeypatch, tmp_path)
    _write_queen_session(tmp_path, QUEEN, "sess_a", {"queen_id": QUEEN, "superseded_by": "sess_b"})
    _write_queen_session(tmp_path, QUEEN, "sess_b", {"queen_id": QUEEN, "superseded_by": "sess_c"})
    _write_queen_session(tmp_path, QUEEN, "sess_c", {"queen_id": QUEEN})

    app = create_app()
    manager = app["manager"]
    resumed = _make_session(agent_id="sess_c", with_queen=False)
    resumed.queen_name = QUEEN
    manager.create_session = AsyncMock(return_value=resumed)

    async with TestClient(TestServer(app)) as client:
        resp = await client.post(
            f"/api/queen/{QUEEN}/session/select",
            json={"session_id": "sess_a"},
        )
        assert resp.status == 200
        data = await resp.json()

    assert data["session_id"] == "sess_c"
    assert data["status"] == "resumed"
    # The chain was walked A -> B -> C before resuming.
    manager.create_session.assert_awaited_once_with(
        colony_id=None,
        queen_resume_from="sess_c",
        initial_prompt=None,
        queen_name=QUEEN,
        initial_phase="independent",
    )


@pytest.mark.asyncio
async def test_select_follows_supersession_chain_to_live_successor(monkeypatch, tmp_path):
    """When the tail of the chain is already live, selecting the retired
    head returns the live successor without spawning a duplicate."""
    _patch_all_queen_storage(monkeypatch, tmp_path)
    _write_queen_session(tmp_path, QUEEN, "sess_a", {"queen_id": QUEEN, "superseded_by": "sess_b"})
    _write_queen_session(tmp_path, QUEEN, "sess_b", {"queen_id": QUEEN, "superseded_by": "sess_c"})
    _write_queen_session(tmp_path, QUEEN, "sess_c", {"queen_id": QUEEN})

    app = create_app()
    manager = app["manager"]
    live_tail = _make_session(agent_id="sess_c", with_queen=False)
    live_tail.queen_name = QUEEN
    # _make_session stamps colony_id=agent_id as generic filler; this test
    # models a DM session, and DM-ness is defined as colony_id is None
    # (select routes colony-bound live sessions to the colony page).
    live_tail.colony_id = None
    manager._sessions["sess_c"] = live_tail
    manager.create_session = AsyncMock()

    async with TestClient(TestServer(app)) as client:
        resp = await client.post(
            f"/api/queen/{QUEEN}/session/select",
            json={"session_id": "sess_a"},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data == {"session_id": "sess_c", "queen_id": QUEEN, "status": "live"}
        # No new session minted — the live tail was reused.
        manager.create_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_select_non_superseded_session_is_unaffected(monkeypatch, tmp_path):
    """Regression guard: a session with no superseded_by resumes itself."""
    _patch_all_queen_storage(monkeypatch, tmp_path)
    _write_queen_session(tmp_path, QUEEN, "sess_plain", {"queen_id": QUEEN})

    app = create_app()
    manager = app["manager"]
    resumed = _make_session(agent_id="sess_plain", with_queen=False)
    resumed.queen_name = QUEEN
    manager.create_session = AsyncMock(return_value=resumed)

    async with TestClient(TestServer(app)) as client:
        resp = await client.post(
            f"/api/queen/{QUEEN}/session/select",
            json={"session_id": "sess_plain"},
        )
        assert resp.status == 200
        data = await resp.json()

    assert data["session_id"] == "sess_plain"
    manager.create_session.assert_awaited_once_with(
        colony_id=None,
        queen_resume_from="sess_plain",
        initial_prompt=None,
        queen_name=QUEEN,
        initial_phase="independent",
    )


# ---------------------------------------------------------------------------
# handle_queen_session — cold-resume resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_queen_session_skips_superseded_on_cold_resume(monkeypatch, tmp_path):
    """Opening the queen must resume the successor, not the retired
    session — even when the retired dir has the NEWER mtime (which the
    plain mtime sort would otherwise pick)."""
    _patch_all_queen_storage(monkeypatch, tmp_path)
    new_dir = _write_queen_session(tmp_path, QUEEN, "sess_new", {"queen_id": QUEEN})
    old_dir = _write_queen_session(tmp_path, QUEEN, "sess_old", {"queen_id": QUEEN, "superseded_by": "sess_new"})
    # Force the retired dir to look most-recent — only the superseded_by
    # skip should keep it from being chosen.
    os.utime(new_dir, (1_000_000, 1_000_000))
    os.utime(old_dir, (2_000_000, 2_000_000))

    app = create_app()
    manager = app["manager"]
    resumed = _make_session(agent_id="sess_new", with_queen=False)
    resumed.queen_name = QUEEN
    manager.create_session = AsyncMock(return_value=resumed)

    async with TestClient(TestServer(app)) as client:
        resp = await client.post(f"/api/queen/{QUEEN}/session", json={})
        assert resp.status == 200
        data = await resp.json()

    assert data["session_id"] == "sess_new"
    assert data["status"] == "resumed"
    assert manager.create_session.await_args.kwargs["queen_resume_from"] == "sess_new"


# ---------------------------------------------------------------------------
# /chat — superseded lock + fork-kickoff re-arm
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_rejects_superseded_session():
    """A session forked away from is locked: /chat returns 409."""
    app = create_app()
    manager = app["manager"]
    session = _make_session(agent_id="retired_session")
    session.superseded_by = "successor_session"
    manager._sessions[session.id] = session

    async with TestClient(TestServer(app)) as client:
        resp = await client.post(
            f"/api/sessions/{session.id}/chat",
            json={"message": "are you still there?"},
        )
        assert resp.status == 409
        data = await resp.json()
        assert data["reason"] == "superseded"
        assert data["superseded_by"] == "successor_session"


@pytest.mark.asyncio
async def test_chat_clears_fork_kickoff_pending():
    """The first genuine user message re-arms new_session on a freshly
    forked session by clearing fork_kickoff_pending."""
    app = create_app()
    manager = app["manager"]
    session = _make_session(agent_id="forked_session")
    session.fork_kickoff_pending = True
    manager._sessions[session.id] = session

    async with TestClient(TestServer(app)) as client:
        resp = await client.post(
            f"/api/sessions/{session.id}/chat",
            json={"message": "now do something else"},
        )
        # The handler may 200 or surface a downstream error, but the flag
        # is cleared unconditionally once the request passes the guards.
        assert resp.status in (200, 202)

    assert session.fork_kickoff_pending is False
