"""A queen's persona from the profile page: read and replace its fields whole, and the page's counts."""

from __future__ import annotations

import json

import pytest
import yaml
from aiohttp.test_utils import TestClient, TestServer

from framework.agents.queen import queen_memory_v2, queen_profiles
from framework.server import routes_queens

QUEEN = "queen_x"
PROFILE = {
    "name": "Fox",
    "title": "The painter",
    "core_traits": "<voice>\nShort lines.\n</voice>\n",
    "skills": "drawing, teasing",
    "hidden_background": {"past_wound": "lost a sketchbook", "deep_motive": "to be remembered"},
}


@pytest.fixture
def queens(tmp_path, monkeypatch):
    for module in (queen_profiles, routes_queens):
        monkeypatch.setattr(module, "QUEENS_DIR", tmp_path)
    folder = tmp_path / QUEEN
    folder.mkdir()
    (folder / "profile.yaml").write_text(yaml.safe_dump(PROFILE, allow_unicode=True, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(routes_queens, "schedule_push", lambda *a, **k: None)
    return tmp_path


async def _client():
    from framework.server.app import create_app

    return TestClient(TestServer(create_app()))


@pytest.mark.asyncio
async def test_reading_her_persona_gives_the_fields_as_written(queens):
    async with await _client() as client:
        body = await (await client.get(f"/api/queen/{QUEEN}/persona")).json()
        missing = await client.get("/api/queen/queen_nobody/persona")

    assert body["persona"] == PROFILE
    assert missing.status == 404


@pytest.mark.asyncio
async def test_replacing_fields_keeps_the_file_readable_and_a_snapshot(queens):
    traits = "<voice>  \nShort lines.\nNo exclamation marks.  \n</voice>\n"

    async with await _client() as client:
        resp = await client.put(f"/api/queen/{QUEEN}/persona", json={"persona": {"core_traits": traits, "hidden_background": None}})
        body = await resp.json()

    assert resp.status == 200
    assert body["persona"]["core_traits"] == "<voice>\nShort lines.\nNo exclamation marks.\n</voice>\n"
    assert "hidden_background" not in body["persona"]
    text = (queens / QUEEN / "profile.yaml").read_text(encoding="utf-8")
    assert "core_traits: |\n  <voice>\n  Short lines.\n" in text
    (snapshot,) = (queens / QUEEN / "_profile_snapshots").glob("profile.yaml.*.pre-dashboard-edit")
    assert yaml.safe_load(snapshot.read_text(encoding="utf-8")) == PROFILE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("persona", "error"),
    [
        ({"name": "  "}, "'name' can't be empty"),
        ({"core_traits": 3}, "'core_traits' must be text"),
        ({"world_lore": {"habitat": 1}}, "'world_lore' must map names to text"),
        ({"behavior_triggers": "often"}, "'behavior_triggers' must be a list of {trigger, reaction} texts"),
        ({"behavior_triggers": [{"trigger": "praise"}]}, "'behavior_triggers' must be a list of {trigger, reaction} texts"),
        ({"voice": "x"}, "Unknown persona field 'voice'"),
    ],
)
async def test_a_bad_field_is_refused_and_nothing_is_written(queens, persona, error):
    before = (queens / QUEEN / "profile.yaml").read_text(encoding="utf-8")

    async with await _client() as client:
        resp = await client.put(f"/api/queen/{QUEEN}/persona", json={"persona": persona})
        body = await resp.json()

    assert resp.status == 400 and body["error"] == error
    assert (queens / QUEEN / "profile.yaml").read_text(encoding="utf-8") == before


@pytest.mark.asyncio
async def test_the_overview_counts_her_memories_and_sessions(queens, monkeypatch):
    memory = queens / "memory"
    memory.mkdir()
    for name, kind in (("a.md", "preference"), ("b.md", "preference"), ("c.md", "feedback")):
        (memory / name).write_text(f"---\nname: {name}\ndescription: d\ntype: {kind}\n---\nbody", encoding="utf-8")
    monkeypatch.setattr(queen_memory_v2, "queen_memory_dir", lambda queen_id: memory)
    for session in ("session_20260710_014648_aaaa1111", "session_20261020_013004_bbbb2222"):
        folder = queens / QUEEN / "sessions" / session
        folder.mkdir(parents=True)
        (folder / "events.jsonl").write_text(json.dumps({"type": "x"}) + "\n", encoding="utf-8")

    async with await _client() as client:
        body = await (await client.get(f"/api/queen/{QUEEN}/overview")).json()

    assert body["memory"] == {"count": 3, "limit": queen_memory_v2.MAX_FILES, "by_type": {"preference": 2, "feedback": 1}}
    assert body["sessions"]["count"] == 2 and body["sessions"]["first"] == "2026-07-10"
    assert body["sessions"]["last_active"]
