"""The Memory page's edits are the owner's, its deletions retire, and every change can be undone."""

from __future__ import annotations

from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import framework.server.routes_memories as routes
from framework.agents.queen import memory_log
from framework.agents.queen.queen_memory_v2 import parse_frontmatter

pytestmark = pytest.mark.asyncio

NOTE = "---\nname: Tea\ndescription: What Ava drinks\ntype: preference\n---\n\nAva drinks oolong.\n"


@pytest.fixture
def memories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "memories"
    monkeypatch.setattr(routes, "MEMORIES_DIR", root)
    monkeypatch.setattr(routes, "schedule_push", lambda *a, **k: None)
    (root / "global").mkdir(parents=True)
    return root


@pytest_asyncio.fixture
async def client(memories: Path):
    app = web.Application()
    routes.register_routes(app)
    async with TestClient(TestServer(app)) as c:
        yield c


async def test_an_edit_on_the_page_makes_the_file_the_owners(client: TestClient, memories: Path):
    memory_log.write(memories / "global", "tea.md", NOTE, author="reflection")

    resp = await client.put("/api/memories/file?path=global/tea.md", json={"content": NOTE.replace("oolong", "sencha")})

    assert resp.status == 200
    body = await resp.json()
    assert body["author"] == "owner"
    with pytest.raises(memory_log.OwnerWritten):
        memory_log.write(memories / "global", "tea.md", NOTE, author="reflection")


async def test_the_list_says_who_wrote_each_file_and_when_it_was_confirmed(client: TestClient, memories: Path):
    memory_log.write(memories / "global", "tea.md", NOTE, author="queen")

    (entry,) = (await (await client.get("/api/memories")).json())["memories"]

    assert entry["author"] == "queen"
    assert entry["confirmed"] == entry["learned"]


async def test_the_log_is_not_listed_as_a_memory(client: TestClient, memories: Path):
    memory_log.write(memories / "global", "tea.md", NOTE, author="queen")

    listed = (await (await client.get("/api/memories")).json())["memories"]

    assert [m["filename"] for m in listed] == ["tea.md"]


async def test_deleting_on_the_page_retires_the_file_and_it_can_be_restored(client: TestClient, memories: Path):
    written = memory_log.write(memories / "global", "tea.md", NOTE, author="reflection")

    assert (await client.delete("/api/memories/file?path=global/tea.md")).status == 200
    assert not (memories / "global" / "tea.md").exists()

    (gone,) = (await (await client.get("/api/memories/retired")).json())["retired"]
    assert (gone["path"], gone["author"], gone["scope"]) == ("global/tea.md", "owner", "global")

    resp = await client.post("/api/memories/restore?path=global/tea.md", json={"n": gone["n"]})
    assert resp.status == 200
    assert (memories / "global" / "tea.md").read_text(encoding="utf-8") == written
    assert (await (await client.get("/api/memories/retired")).json())["retired"] == []


async def test_history_lists_every_change_to_a_file(client: TestClient, memories: Path):
    memory_log.write(memories / "global", "tea.md", NOTE, author="reflection", reason="she said so")
    await client.put("/api/memories/file?path=global/tea.md", json={"content": NOTE.replace("oolong", "sencha")})

    changes = (await (await client.get("/api/memories/history?path=global/tea.md")).json())["changes"]

    assert [(c["n"], c["author"], c["reason"]) for c in changes] == [(0, "reflection", "she said so"), (1, "owner", "edited on the Memory page")]


async def test_restoring_an_unknown_change_is_not_found(client: TestClient, memories: Path):
    memory_log.write(memories / "global", "tea.md", NOTE, author="reflection")

    resp = await client.post("/api/memories/restore?path=global/tea.md", json={"n": 9})

    assert resp.status == 404


@pytest.mark.parametrize("body", [{}, {"n": "0"}, {"n": True}])
async def test_restoring_needs_a_change_number(client: TestClient, memories: Path, body: dict):
    resp = await client.post("/api/memories/restore?path=global/tea.md", json=body)

    assert resp.status == 400


async def test_a_seeded_memory_is_nobodys_so_her_reflection_can_build_on_it(client: TestClient, memories: Path):
    resp = await client.post("/api/memories/file?path=global/company.md", json={"name": "Company", "body": "Ava runs a tea shop."})

    assert resp.status == 200
    text = (memories / "global" / "company.md").read_text(encoding="utf-8")
    assert "author" not in parse_frontmatter(text)
    memory_log.write(memories / "global", "company.md", text.replace("tea shop", "tea house"), author="reflection")


async def test_history_refuses_a_path_outside_the_memories(client: TestClient, memories: Path):
    resp = await client.get("/api/memories/history?path=../secrets.md")

    assert resp.status == 400
