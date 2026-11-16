"""The positions in the queen catalog: taking a queen out of it, and putting her back as she was."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
import yaml
from aiohttp.test_utils import TestClient, TestServer

from framework.agents.queen import queen_profiles
from framework.server import routes_queens


@pytest.fixture
def queens(tmp_path, monkeypatch):
    for module in (queen_profiles, routes_queens):
        monkeypatch.setattr(module, "QUEENS_DIR", tmp_path)
    (tmp_path / "queen_mira").mkdir()
    (tmp_path / "queen_mira" / "profile.yaml").write_text(yaml.safe_dump({"name": "Mira", "title": "Cartographer"}), encoding="utf-8")
    return tmp_path


async def _client():
    from framework.server.app import create_app

    return TestClient(TestServer(create_app()))


def _ids(body: dict) -> set[str]:
    return {q["id"] for q in body["queens"]}


@pytest.mark.asyncio
async def test_a_removed_queen_leaves_the_catalog_and_comes_back_as_she_was(queens):
    async with await _client() as client:
        removed = await client.post("/api/queen/queen_legal/remove")
        await client.post("/api/queen/queen_mira/remove")
        listed = await (await client.get("/api/queen/profiles")).json()
        offered = await (await client.get("/api/queen/removed")).json()
        restored = await client.post("/api/queen/queen_mira/restore")
        after = await (await client.get("/api/queen/profiles")).json()

    assert removed.status == 200 and restored.status == 200
    assert not {"queen_legal", "queen_mira"} & _ids(listed)
    assert _ids(offered) == {"queen_legal", "queen_mira"}
    assert "queen_mira" in _ids(after) and "queen_legal" not in _ids(after)
    # Removing never touched her files.
    assert (queens / "queen_mira" / "profile.yaml").exists()


@pytest.mark.asyncio
async def test_a_queen_hive_doesnt_know_cant_be_removed(queens):
    async with await _client() as client:
        resp = await client.post("/api/queen/queen_nobody/remove")

    assert resp.status == 404
    assert not (queens / queen_profiles.CATALOG_FILE).exists()


class _Classifier:
    """Answers with the queen it was told to, and keeps the prompt it was shown."""

    def __init__(self, queen_id: str) -> None:
        self.queen_id = queen_id
        self.system = ""

    async def acomplete(self, *, messages, system, max_tokens, json_mode):
        self.system = system
        return SimpleNamespace(content=json.dumps({"queen_id": self.queen_id, "reason": "her field", "colony_name": "contracts"}))


@pytest.mark.asyncio
async def test_routing_neither_offers_nor_picks_a_removed_queen(queens):
    queen_profiles.set_queen_removed("queen_legal", True)
    llm = _Classifier("queen_legal")

    selection = await queen_profiles.select_queen_and_colony("Review this contract for me", llm)

    assert "queen_legal" not in llm.system
    assert selection.queen_id != "queen_legal"
