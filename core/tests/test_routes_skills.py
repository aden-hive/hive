"""HTTP integration tests for the skills routes.

Covers the per-queen and aggregated-library surfaces plus the multipart
upload handler. Uses aiohttp's TestClient directly (no pytest-aiohttp
plugin), which is why each test sets up its own client.
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from framework.server.routes_skills import register_routes
from framework.skills.manager import SkillsManager
from framework.skills.overrides import (
    OverrideEntry,
    Provenance,
    SkillOverrideStore,
)

pytestmark = pytest.mark.asyncio


class _StubSessionManager:
    """Tiny stand-in that satisfies the iter_* contracts used by routes.

    The routes_skills handlers call ``manager.iter_queen_sessions`` and
    ``manager.iter_colony_runtimes`` to find live managers to reload.
    In-process tests don't spin up runtimes, so these iterators yield
    nothing — the routes fall back to the admin manager built from disk.
    ``sessions`` are the live sessions the skill-install routes look up.
    """

    def __init__(self, sessions: dict | None = None) -> None:
        self._sessions = sessions or {}

    def iter_queen_sessions(self, queen_id: str):
        return iter([])

    def iter_colony_runtimes(self, *, queen_id=None, colony_id=None):
        return iter([])

    def get_session(self, session_id: str):
        return self._sessions.get(session_id)

    def list_sessions(self) -> list:
        return list(self._sessions.values())


def _build_app(manager: _StubSessionManager | None = None) -> web.Application:
    application = web.Application()
    application["manager"] = manager or _StubSessionManager()
    register_routes(application)
    return application


@pytest_asyncio.fixture
async def client() -> AsyncIterator[TestClient]:
    app = _build_app()
    server = TestServer(app)
    async with TestClient(server) as tc:
        yield tc


@pytest.fixture
def _seed_queen(tmp_path: Path):
    """Write a queen profile so _queen_scope recognises the id."""
    queen_home = Path.home() / ".hive" / "agents" / "queens" / "ops"
    queen_home.mkdir(parents=True, exist_ok=True)
    (queen_home / "profile.yaml").write_text("name: Ops\ntitle: Ops queen\n", encoding="utf-8")
    return queen_home


@pytest.fixture
def _seed_colony(tmp_path: Path):
    colony_home = Path.home() / ".hive" / "colonies" / "research_one"
    colony_home.mkdir(parents=True, exist_ok=True)
    return colony_home


async def test_get_queen_skills_returns_empty_for_fresh_queen(client: TestClient, _seed_queen) -> None:
    resp = await client.get("/api/queen/ops/skills")
    assert resp.status == 200
    data = await resp.json()
    assert data["queen_id"] == "ops"
    assert data["all_defaults_disabled"] is False
    # Fresh install → framework default skills show up via discovery.
    assert isinstance(data["skills"], list)


async def test_create_queen_skill_writes_file_and_override(client: TestClient, _seed_queen) -> None:
    payload = {
        "name": "ops-runbook",
        "description": "Runbook for ops",
        "body": "## Steps\n1. Check\n",
        "enabled": True,
    }
    resp = await client.post("/api/queen/ops/skills", json=payload)
    assert resp.status == 201
    data = await resp.json()
    assert data["name"] == "ops-runbook"
    # Verify files were written to the queen skill dir.
    skill_md = _seed_queen / "skills" / "ops-runbook" / "SKILL.md"
    assert skill_md.exists()
    # Verify override was registered with USER_UI_CREATED provenance.
    store = SkillOverrideStore.load(_seed_queen / "skills_overrides.json")
    entry = store.get("ops-runbook")
    assert entry is not None
    assert entry.provenance == Provenance.USER_UI_CREATED
    assert entry.enabled is True


async def test_patch_queen_skill_toggles_enabled(client: TestClient, _seed_queen) -> None:
    await client.post(
        "/api/queen/ops/skills",
        json={"name": "ops-a", "description": "a", "body": "body"},
    )
    resp = await client.patch(
        "/api/queen/ops/skills/ops-a",
        json={"enabled": False},
    )
    assert resp.status == 200
    store = SkillOverrideStore.load(_seed_queen / "skills_overrides.json")
    assert store.get("ops-a").enabled is False


async def test_delete_queen_skill_removes_files(client: TestClient, _seed_queen) -> None:
    await client.post(
        "/api/queen/ops/skills",
        json={"name": "tmp-skill", "description": "d", "body": "body"},
    )
    skill_dir = _seed_queen / "skills" / "tmp-skill"
    assert skill_dir.exists()

    resp = await client.delete("/api/queen/ops/skills/tmp-skill")
    assert resp.status == 200
    assert not skill_dir.exists()
    store = SkillOverrideStore.load(_seed_queen / "skills_overrides.json")
    assert "tmp-skill" in store.deleted_ui_skills


async def test_delete_framework_skill_is_refused(client: TestClient, _seed_queen) -> None:
    # Pre-seed an override entry with framework provenance — simulates the
    # user toggling a framework default so the override exists on disk.
    store = SkillOverrideStore.load(_seed_queen / "skills_overrides.json")
    store.upsert(
        "hive.writing-hive-skills",
        OverrideEntry(enabled=False, provenance=Provenance.FRAMEWORK),
    )
    store.save()

    resp = await client.delete("/api/queen/ops/skills/hive.writing-hive-skills")
    assert resp.status == 403


async def test_upload_markdown_places_in_user_library(client: TestClient) -> None:
    skill_md = "---\nname: from-upload\ndescription: Uploaded skill\n---\n\n## Body\nHi.\n"
    form = {
        "file": skill_md.encode("utf-8"),
        "scope": "user",
        "enabled": "true",
    }
    # Use multipart writer pattern: aiohttp test client auto-serializes dicts.
    data = _as_form(form, filename="SKILL.md")
    resp = await client.post("/api/skills/upload", data=data)
    assert resp.status == 201
    body = await resp.json()
    assert body["name"] == "from-upload"
    assert (Path.home() / ".hive" / "skills" / "from-upload" / "SKILL.md").exists()


async def test_upload_zip_bundle_places_in_queen_scope(client: TestClient, _seed_queen) -> None:
    # Build a zip in memory with SKILL.md + a supporting file.
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "SKILL.md",
            "---\nname: zipped-skill\ndescription: From zip\n---\n\nbody\n",
        )
        z.writestr("scripts/helper.py", "print('hi')\n")
    payload = buf.getvalue()
    form = {
        "file": payload,
        "scope": "queen",
        "target_id": "ops",
        "enabled": "true",
    }
    data = _as_form(form, filename="bundle.zip")
    resp = await client.post("/api/skills/upload", data=data)
    assert resp.status == 201
    skill_dir = _seed_queen / "skills" / "zipped-skill"
    assert (skill_dir / "SKILL.md").exists()
    assert (skill_dir / "scripts" / "helper.py").exists()


async def test_colony_authored_skills_surface_in_library(client: TestClient, _seed_colony) -> None:
    """Colonies no longer have their own skill config, but skills written
    into a colony's dir (by ``create_colony`` / ``write_skill``) — in both
    the flat ``skills/`` and the legacy nested ``.hive/skills/`` layouts —
    must still surface in the aggregated library with colony_ui scope and
    queen-authored provenance.
    """
    flat_dir = _seed_colony / "skills" / "flat-colony-skill"
    flat_dir.mkdir(parents=True)
    (flat_dir / "SKILL.md").write_text(
        "---\nname: flat-colony-skill\ndescription: Flat layout\n---\n\nbody\n",
        encoding="utf-8",
    )
    nested_dir = _seed_colony / ".hive" / "skills" / "legacy-colony-skill"
    nested_dir.mkdir(parents=True)
    (nested_dir / "SKILL.md").write_text(
        "---\nname: legacy-colony-skill\ndescription: Legacy nested\n---\n\nbody\n",
        encoding="utf-8",
    )

    resp = await client.get("/api/skills")
    assert resp.status == 200
    rows = {r["name"]: r for r in (await resp.json())["skills"]}
    for name in ("flat-colony-skill", "legacy-colony-skill"):
        assert name in rows
        assert rows[name]["source_scope"] == "colony_ui"
        assert rows[name]["provenance"] == "queen_created"
        assert rows[name]["owner"] == {"type": "colony", "id": "research_one", "name": "research_one"}


async def test_colony_config_routes_are_gone(client: TestClient, _seed_colony) -> None:
    """Per-colony skill configuration was removed — colonies inherit their
    owning queen's config. The old routes must not resolve.
    """
    resp = await client.get("/api/colonies/research_one/skills")
    assert resp.status == 404
    resp = await client.patch(
        "/api/colonies/research_one/skills/anything",
        json={"enabled": False},
    )
    assert resp.status == 404


async def test_list_scopes_enumerates_queens_and_colonies(client: TestClient, _seed_queen, _seed_colony) -> None:
    resp = await client.get("/api/skills/scopes")
    assert resp.status == 200
    data = await resp.json()
    assert any(q["id"] == "ops" for q in data["queens"])
    assert any(c["name"] == "research_one" for c in data["colonies"])


# ---------------------------------------------------------------------------
# A queen's requests to add a skill to the shared library
# ---------------------------------------------------------------------------


def _session_dir(session_id: str = "session_ava_1") -> Path:
    import framework.config as config

    path = config.QUEENS_DIR / "queen_ava" / "sessions" / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _file_request(session_dir: Path, name: str = "house-style") -> dict:
    from framework.skills import install_requests
    from framework.skills.skill_writer import build_draft

    draft, _ = build_draft(
        skill_name=name,
        skill_description="How Ava formats her reports.",
        skill_body="# House style\n\nLead with the answer.\n",
        skill_files=[{"path": "scripts/check.py", "content": "print('ok')\n"}],
    )
    return install_requests.add_request(session_dir, draft)


class _CountingSkillsManager(SkillsManager):
    def __init__(self) -> None:
        super().__init__()
        self.reloads = 0

    def reload(self) -> None:
        self.reloads += 1


def _live_session(session_dir: Path):
    """A running queen session: her loop takes notes, her catalog counts reloads."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from framework.host.event_bus import EventBus

    queen = SimpleNamespace(inject_event=AsyncMock())
    return SimpleNamespace(
        id=session_dir.name,
        queen_name="queen_ava",
        queen_dir=session_dir,
        queen_executor=SimpleNamespace(node_registry={"queen": queen}),
        event_bus=EventBus(),
        phase_state=SimpleNamespace(skills_manager=_CountingSkillsManager()),
        colony=None,
    )


async def test_pending_skill_installs_carry_the_skill_and_whether_it_replaces_one(client: TestClient) -> None:
    import framework.config as config

    session_dir = _session_dir()
    request = _file_request(session_dir)
    _file_request(session_dir, name="fresh-skill")
    existing = config.HIVE_HOME / "skills" / "house-style"
    existing.mkdir(parents=True)

    resp = await client.get(f"/api/sessions/{session_dir.name}/skill-installs")

    assert resp.status == 200
    rows = (await resp.json())["requests"]
    assert [(r["name"], r["replaces"]) for r in rows] == [("house-style", True), ("fresh-skill", False)]
    assert rows[0]["id"] == request["id"]
    assert rows[0]["files"] == [{"path": "scripts/check.py", "content": "print('ok')\n"}]


async def test_approving_installs_the_stored_skill_and_tells_the_queen() -> None:
    import framework.config as config
    from framework.host.event_bus import EventType
    from framework.skills import install_requests

    session_dir = _session_dir()
    request = _file_request(session_dir)
    live = _live_session(session_dir)
    decided = []

    async def on_event(event) -> None:
        decided.append(event.data)

    live.event_bus.subscribe(event_types=[EventType.SKILL_INSTALL_DECIDED], handler=on_event)
    app = _build_app(_StubSessionManager({live.id: live}))
    async with TestClient(TestServer(app)) as tc:
        resp = await tc.post(f"/api/sessions/{live.id}/skill-installs/{request['id']}", json={"decision": "approve"})
        result = await resp.json()

    assert resp.status == 200
    assert result["queen_told"] is True
    installed = config.HIVE_HOME / "skills" / "house-style"
    assert "Lead with the answer." in (installed / "SKILL.md").read_text(encoding="utf-8")
    assert (installed / "scripts" / "check.py").read_text(encoding="utf-8") == "print('ok')\n"
    assert install_requests.pending_requests(session_dir) == []
    assert live.phase_state.skills_manager.reloads == 1
    [note] = live.queen_executor.node_registry["queen"].inject_event.await_args.args
    assert "approved" in note and "house-style" in note
    assert decided == [{"request_id": request["id"], "name": "house-style", "decision": "approve"}]


async def test_denying_installs_nothing(client: TestClient) -> None:
    import framework.config as config
    from framework.skills import install_requests

    session_dir = _session_dir()
    request = _file_request(session_dir)

    resp = await client.post(f"/api/sessions/{session_dir.name}/skill-installs/{request['id']}", json={"decision": "deny"})

    assert resp.status == 200
    assert (await resp.json())["queen_told"] is False  # her session isn't running
    assert not (config.HIVE_HOME / "skills" / "house-style").exists()
    assert install_requests.pending_requests(session_dir) == []


async def test_a_request_is_decided_once(client: TestClient) -> None:
    session_dir = _session_dir()
    request = _file_request(session_dir)
    url = f"/api/sessions/{session_dir.name}/skill-installs/{request['id']}"
    await client.post(url, json={"decision": "deny"})

    resp = await client.post(url, json={"decision": "approve"})

    assert resp.status == 409


async def test_deciding_an_unknown_request_or_session_is_not_found(client: TestClient) -> None:
    session_dir = _session_dir()

    unknown_request = await client.post(f"/api/sessions/{session_dir.name}/skill-installs/nope", json={"decision": "approve"})
    unknown_session = await client.get("/api/sessions/session_nobody/skill-installs")

    assert (unknown_request.status, unknown_session.status) == (404, 404)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_form(fields: dict, *, filename: str):
    """Build aiohttp FormData; bytes entries are attached as file parts."""
    from aiohttp import FormData

    fd = FormData()
    for key, value in fields.items():
        if isinstance(value, bytes):
            fd.add_field(key, value, filename=filename)
        else:
            fd.add_field(key, value)
    return fd
