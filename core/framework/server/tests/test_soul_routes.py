"""A queen's soul from the dashboard: read it, edit it, decide on proposals, roll back, reflect now."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

import framework.config as hive_config
from framework.agents.queen import soul as soul_mod, soul_reflection as sr
from framework.agents.queen.soul import Edit, Proposal
from framework.server import routes_soul

QUEEN = "queen_x"
SECTIONS = [{"key": "now", "title": "Now", "limit": 40}, {"key": "people", "title": "Me and them", "limit": 60, "evidence": 2}]


@pytest.fixture
def home(tmp_path, monkeypatch):
    config = {"soul": {"queens": {QUEEN: {"enabled": True, "sections": SECTIONS}}}}
    monkeypatch.setattr(hive_config, "get_hive_config", lambda: config)
    for module in (soul_mod, sr):
        monkeypatch.setattr(module, "QUEENS_DIR", tmp_path / "queens")

    def profile(queen_id):
        if queen_id not in (QUEEN, "queen_plain"):
            raise FileNotFoundError(queen_id)
        return {"name": "Fox"}

    monkeypatch.setattr(routes_soul, "load_queen_profile", profile)
    return tmp_path


async def _client():
    from framework.server.app import create_app

    return TestClient(TestServer(create_app()))


@pytest.mark.asyncio
async def test_reading_a_soul_shows_its_sections_and_their_room(home):
    soul_mod.save(QUEEN, hive_config.get_soul_config(QUEEN), {"now": [soul_mod.Item("drawing a lantern", "2026-10-20")]}, author="owner", note="v1")

    async with await _client() as client:
        view = await (await client.get(f"/api/queen/{QUEEN}/soul")).json()
        plain = await (await client.get("/api/queen/queen_plain/soul")).json()
        missing = await client.get("/api/queen/queen_nobody/soul")

    assert (view["enabled"], view["version"], view["mode"]) == (True, 1, "review")
    assert view["sections"][0] == {
        "key": "now",
        "title": "Now",
        "limit": 40,
        "used": 17,
        "max_age_days": None,
        "evidence": 1,
        "items": [{"text": "drawing a lantern", "date": "2026-10-20"}],
    }
    assert view["proposal"] is None and view["history"][0]["note"] == "v1"
    assert plain == {"queen_id": "queen_plain", "enabled": False}
    assert missing.status == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sections", "status", "error"),
    [
        ({"now": [{"text": "x" * 41}]}, 400, "Now: 41/40 characters"),
        ({"later": []}, 400, "Unknown sections: later"),
        ({"now": [{"text": "ok", "date": "tomorrow"}]}, 400, "Bad date"),
    ],
)
async def test_a_bad_edit_is_refused_and_nothing_changes(home, sections, status, error):
    async with await _client() as client:
        resp = await client.put(f"/api/queen/{QUEEN}/soul", json={"sections": sections})
        body = await resp.json()

    assert resp.status == status and error in body["error"]
    assert soul_mod.load(QUEEN).version == 0


@pytest.mark.asyncio
async def test_editing_by_hand_makes_a_new_version(home):
    async with await _client() as client:
        view = await (
            await client.put(
                f"/api/queen/{QUEEN}/soul", json={"sections": {"now": [{"text": "  a  cat next ", "date": "2026-10-21"}, {"text": " "}]}}
            )
        ).json()

    assert view["version"] == 1
    assert view["sections"][0]["items"] == [{"text": "a cat next", "date": "2026-10-21"}]
    assert view["history"][0]["author"] == "owner"


@pytest.mark.asyncio
async def test_approving_part_of_a_proposal_and_deciding_twice(home):
    proposal = Proposal(
        id="2026-10-21-040000",
        created_at="2026-10-21T04:00:00+08:00",
        base_version=0,
        edits=[Edit(op="add", section="now", text="a cat next", date="2026-10-21"), Edit(op="add", section="now", text="and a fox")],
    )
    soul_mod.save_proposal(QUEEN, proposal)

    async with await _client() as client:
        before = await (await client.get(f"/api/queen/{QUEEN}/soul")).json()
        view = await (await client.post(f"/api/queen/{QUEEN}/soul/proposals/{proposal.id}/decide", json={"accept": [0]})).json()
        again = await client.post(f"/api/queen/{QUEEN}/soul/proposals/{proposal.id}/decide", json={"accept": None})
        bad = await client.post(f"/api/queen/{QUEEN}/soul/proposals/{proposal.id}/decide", json={"accept": "all"})
        missing = await client.post(f"/api/queen/{QUEEN}/soul/proposals/nope/decide", json={})

    assert before["proposal"]["id"] == proposal.id
    assert view["sections"][0]["items"] == [{"text": "a cat next", "date": "2026-10-21"}]
    assert view["proposal"] is None
    assert again.status == 409 and missing.status == 404
    assert bad.status in (400, 409)


@pytest.mark.asyncio
async def test_rolling_back_to_an_earlier_version(home):
    cfg = hive_config.get_soul_config(QUEEN)
    soul_mod.save(QUEEN, cfg, {"now": [soul_mod.Item("one")]}, author="owner", note="v1")
    soul_mod.save(QUEEN, cfg, {"now": [soul_mod.Item("two")]}, author="owner", note="v2")

    async with await _client() as client:
        view = await (await client.post(f"/api/queen/{QUEEN}/soul/rollback", json={"version": 1})).json()
        bad = await client.post(f"/api/queen/{QUEEN}/soul/rollback", json={"version": 7})

    assert view["version"] == 3 and view["sections"][0]["items"] == [{"text": "one", "date": ""}]
    assert bad.status == 400


@pytest.mark.asyncio
async def test_reflecting_now_runs_in_the_background_and_waits_for_a_pending_proposal(home, monkeypatch):
    reflected = AsyncMock(return_value=None)
    monkeypatch.setattr(sr, "reflect", reflected)
    monkeypatch.setattr(sr, "llm_for", lambda queen_id, cfg, manager: "llm")

    async with await _client() as client:
        started = await client.post(f"/api/queen/{QUEEN}/soul/reflect", json={"bootstrap": True})
        await asyncio.sleep(0.05)
        soul_mod.save_proposal(
            QUEEN, Proposal(id="2026-10-21-040000", created_at="", base_version=0, edits=[Edit(op="add", section="now", text="x")])
        )
        held = await client.post(f"/api/queen/{QUEEN}/soul/reflect", json={})
        held_body = await held.json()

    assert started.status == 202
    reflected.assert_awaited_once()
    assert reflected.await_args.kwargs["bootstrap"] is True
    assert held.status == 409 and "waiting proposal" in held_body["error"]


@pytest.mark.asyncio
async def test_a_queen_without_a_soul_cannot_be_edited(home):
    async with await _client() as client:
        resp = await client.put("/api/queen/queen_plain/soul", json={"sections": {}})
        body = await resp.json()

    assert resp.status == 409 and "has no soul" in body["error"]
    assert json.dumps(body)


@pytest.mark.asyncio
async def test_trying_her_out_needs_probe_questions_and_runs_in_the_background(home, monkeypatch):
    from framework.agents.queen import soul_probes

    probed = AsyncMock(return_value=[])
    monkeypatch.setattr(soul_probes, "probe", probed)
    monkeypatch.setattr(sr, "llm_for", lambda queen_id, cfg, manager: "llm")
    proposal = Proposal(id="2026-10-21-040000", created_at="", base_version=0, edits=[Edit(op="add", section="now", text="x")])
    soul_mod.save_proposal(QUEEN, proposal)

    async with await _client() as client:
        without = await client.post(f"/api/queen/{QUEEN}/soul/proposals/{proposal.id}/probe")
        (soul_mod.soul_dir(QUEEN) / soul_probes.PROBES_FILE).write_text(json.dumps([{"q": "hi"}]), encoding="utf-8")
        view = await (await client.get(f"/api/queen/{QUEEN}/soul")).json()
        started = await client.post(f"/api/queen/{QUEEN}/soul/proposals/{proposal.id}/probe")
        await asyncio.sleep(0.05)
        missing = await client.post(f"/api/queen/{QUEEN}/soul/proposals/nope/probe")

    assert without.status == 409
    assert view["probes"] == 1 and view["probing"] is False
    assert started.status == 202
    probed.assert_awaited_once()
    assert missing.status == 404
