"""HTTP integration tests for the skills routes.

Covers the per-queen, per-colony, and aggregated-library surfaces plus
the multipart upload handler. Uses aiohttp's TestClient directly (no
pytest-aiohttp plugin), which is why each test sets up its own client.
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
    """

    def iter_queen_sessions(self, queen_id: str):
        return iter([])

    def iter_colony_runtimes(self, *, queen_id=None, colony_name=None):
        return iter([])


def _build_app() -> web.Application:
    application = web.Application()
    application["manager"] = _StubSessionManager()
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
        "hive.note-taking",
        OverrideEntry(enabled=False, provenance=Provenance.FRAMEWORK),
    )
    store.save()

    resp = await client.delete("/api/queen/ops/skills/hive.note-taking")
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


async def test_patch_does_not_mislabel_legacy_colony_skill_as_framework(client: TestClient, _seed_colony) -> None:
    """Regression: toggling a legacy colony skill (no ledger entry yet)
    must not stamp provenance=FRAMEWORK on the new entry. Before the fix,
    the first PATCH wrote FRAMEWORK and the next GET displayed 'Framework'
    instead of the queen-authored label.
    """
    skill_dir = _seed_colony / ".hive" / "skills" / "legacy-queen-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: legacy-queen-skill\ndescription: From create_colony\n---\n\nbody\n",
        encoding="utf-8",
    )

    resp = await client.patch(
        "/api/colonies/research_one/skills/legacy-queen-skill",
        json={"enabled": False},
    )
    assert resp.status == 200

    list_resp = await client.get("/api/colonies/research_one/skills")
    rows = {r["name"]: r for r in (await list_resp.json())["skills"]}
    assert rows["legacy-queen-skill"]["provenance"] == "queen_created"
    assert rows["legacy-queen-skill"]["enabled"] is False


async def test_colony_skill_is_editable_even_without_override_entry(client: TestClient, _seed_colony) -> None:
    """Regression: a SKILL.md dropped into a colony's .hive/skills dir
    (e.g. from a pre-override-store colony) must still be marked editable
    when listed via /api/colonies/{name}/skills. The admin manager used
    to set project_root=colony_home, which retagged the skill as
    source_scope='project' and fell back to PROJECT_DROPPED provenance —
    flipping editable to False.
    """
    # Write a bare SKILL.md directly; no override ledger entry.
    skill_dir = _seed_colony / ".hive" / "skills" / "legacy-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: legacy-skill\ndescription: A legacy\n---\n\nbody\n",
        encoding="utf-8",
    )

    resp = await client.get("/api/colonies/research_one/skills")
    assert resp.status == 200
    data = await resp.json()
    rows = {r["name"]: r for r in data["skills"]}
    assert "legacy-skill" in rows
    assert rows["legacy-skill"]["editable"] is True
    assert rows["legacy-skill"]["source_scope"] == "colony_ui"
    # Legacy colony skills (no override ledger entry) were authored by
    # create_colony() before the ledger existed — the fallback provenance
    # must reflect that, not be misreported as user-UI-created.
    assert rows["legacy-skill"]["provenance"] == "queen_created"


async def test_list_scopes_enumerates_queens_and_colonies(client: TestClient, _seed_queen, _seed_colony) -> None:
    resp = await client.get("/api/skills/scopes")
    assert resp.status == 200
    data = await resp.json()
    assert any(q["id"] == "ops" for q in data["queens"])
    assert any(c["name"] == "research_one" for c in data["colonies"])


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
