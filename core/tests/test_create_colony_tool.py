"""Tests for the queen-side ``create_colony`` tool.

New contract (two-step flow):

1. The queen authors a skill folder out-of-band (via write_file etc.)
   containing a SKILL.md with YAML frontmatter {name, description} and
   an optional body.
2. The queen calls ``create_colony(colony_name, task, skill_path)``
   pointing at that folder. The tool validates the folder, installs it
   under ``~/.hive/skills/{name}/`` if it's not already there, and
   forks the session into a colony.

We monkeypatch ``fork_session_into_colony`` so the test doesn't need a
real queen / session directory. We also redirect ``$HOME`` so the test's
skill installation lands in a tmp tree, not the real user home.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from framework.host.event_bus import EventBus
from framework.llm.provider import ToolUse
from framework.loader.tool_registry import ToolRegistry
from framework.tools.queen_lifecycle_tools import register_queen_lifecycle_tools


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self, sid: str = "session_test_create_colony"):
        self.id = sid
        self.colony = None
        self.colony_runtime = None
        self.event_bus = EventBus()
        self.worker_path = None
        self.available_triggers: dict = {}
        self.active_trigger_ids: set = set()


def _make_executor():
    """Build a tool executor with create_colony registered."""
    registry = ToolRegistry()
    session = _FakeSession()
    register_queen_lifecycle_tools(registry, session=session, session_id=session.id)
    return registry.get_executor(), session


async def _call(executor, **inputs) -> dict:
    result = executor(
        ToolUse(id="tu_create_colony", name="create_colony", input=inputs)
    )
    if asyncio.iscoroutine(result):
        result = await result
    return json.loads(result.content)


@pytest.fixture
def patched_home(tmp_path, monkeypatch):
    """Redirect $HOME so ~/.hive/skills/ lands in tmp_path."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def patched_fork(monkeypatch):
    """Stub out fork_session_into_colony so we don't need a real queen."""
    calls: list[dict] = []

    async def _stub_fork(*, session: Any, colony_name: str, task: str) -> dict:
        calls.append({"session": session, "colony_name": colony_name, "task": task})
        return {
            "colony_path": f"/tmp/fake_colonies/{colony_name}",
            "colony_name": colony_name,
            "queen_session_id": "session_fake_fork_id",
            "is_new": True,
        }

    monkeypatch.setattr(
        "framework.server.routes_execution.fork_session_into_colony",
        _stub_fork,
    )
    return calls


def _write_skill(
    root: Path,
    *,
    dir_name: str,
    fm_name: str,
    description: str = "Default test skill description with enough text.",
    body: str = "## Body\n\nOperational details go here.\n",
) -> Path:
    """Write a valid skill folder under ``root`` and return its path."""
    skill_dir = root / dir_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        "---\n"
        f"name: {fm_name}\n"
        f'description: "{description}"\n'
        "---\n\n"
        f"{body}",
        encoding="utf-8",
    )
    return skill_dir


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_external_folder_is_copied_into_skills_root(
    tmp_path: Path, patched_home: Path, patched_fork: list[dict]
) -> None:
    """Skill authored outside ~/.hive/skills/ is copied in on install."""
    executor, session = _make_executor()

    # Queen authors skill in a scratch dir, not under ~/.hive/skills/
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    skill_src = _write_skill(
        scratch,
        dir_name="honeycomb-api-protocol",
        fm_name="honeycomb-api-protocol",
        description=(
            "How to query the HoneyComb staging API for ticker, pool, "
            "and trade data. Covers auth, pagination, pool detail "
            "shape. Use when fetching market data."
        ),
        body=(
            "## HoneyComb API Operational Protocol\n\n"
            "Auth: Bearer token from ~/.hive/credentials/honeycomb.json.\n"
            "Pagination: ?page=1&page_size=50 (max 50 per page).\n"
            "Endpoints:\n"
            "- /api/ticker — list tickers\n"
            "- /api/ticker/{id} — pool detail\n"
        ),
    )

    payload = await _call(
        executor,
        colony_name="honeycomb_research",
        task=(
            "Build a daily honeycomb market report covering top gainers, "
            "losers, volume leaders, and category breakdowns."
        ),
        skill_path=str(skill_src),
    )

    assert payload.get("status") == "created", f"Tool error: {payload}"
    assert payload["colony_name"] == "honeycomb_research"
    assert payload["skill_name"] == "honeycomb-api-protocol"

    # The skill was installed under ~/.hive/skills/
    installed = patched_home / ".hive" / "skills" / "honeycomb-api-protocol" / "SKILL.md"
    assert installed.exists()
    assert "HoneyComb API Operational Protocol" in installed.read_text(encoding="utf-8")

    # Fork was called with the right args
    assert len(patched_fork) == 1
    assert patched_fork[0]["colony_name"] == "honeycomb_research"
    assert "honeycomb market report" in patched_fork[0]["task"]
    assert patched_fork[0]["session"] is session


@pytest.mark.asyncio
async def test_happy_path_in_place_authored_skill(
    patched_home: Path, patched_fork: list[dict]
) -> None:
    """Skill authored directly at ~/.hive/skills/{name}/ is accepted in-place."""
    executor, _ = _make_executor()

    skills_root = patched_home / ".hive" / "skills"
    skills_root.mkdir(parents=True)
    skill_src = _write_skill(
        skills_root,
        dir_name="in-place-skill",
        fm_name="in-place-skill",
        description="An in-place skill.",
        body="Contents that are already at the right location." * 3,
    )

    payload = await _call(
        executor,
        colony_name="in_place_colony",
        task="task text",
        skill_path=str(skill_src),
    )

    assert payload.get("status") == "created", payload
    installed = skills_root / "in-place-skill" / "SKILL.md"
    assert installed.exists()
    assert len(patched_fork) == 1


# ---------------------------------------------------------------------------
# Validation failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_skill_path_rejected(patched_home, patched_fork) -> None:
    executor, _ = _make_executor()
    payload = await _call(
        executor,
        colony_name="ok_name",
        task="t",
        skill_path=str(patched_home / "does_not_exist"),
    )
    assert "error" in payload
    assert "does not exist" in payload["error"]
    assert len(patched_fork) == 0


@pytest.mark.asyncio
async def test_skill_path_is_file_not_directory_rejected(
    tmp_path, patched_home, patched_fork
) -> None:
    executor, _ = _make_executor()
    bogus = tmp_path / "not-a-dir.md"
    bogus.write_text("hi", encoding="utf-8")
    payload = await _call(
        executor,
        colony_name="ok_name",
        task="t",
        skill_path=str(bogus),
    )
    assert "error" in payload
    assert "must be a directory" in payload["error"]
    assert len(patched_fork) == 0


@pytest.mark.asyncio
async def test_skill_missing_skill_md_rejected(
    tmp_path, patched_home, patched_fork
) -> None:
    executor, _ = _make_executor()
    folder = tmp_path / "no-skill-md"
    folder.mkdir()
    payload = await _call(
        executor,
        colony_name="ok_name",
        task="t",
        skill_path=str(folder),
    )
    assert "error" in payload
    assert "SKILL.md" in payload["error"]
    assert len(patched_fork) == 0


@pytest.mark.asyncio
async def test_skill_md_missing_frontmatter_marker_rejected(
    tmp_path, patched_home, patched_fork
) -> None:
    executor, _ = _make_executor()
    folder = tmp_path / "broken-fm"
    folder.mkdir()
    (folder / "SKILL.md").write_text(
        "no frontmatter here, just body\n", encoding="utf-8"
    )
    payload = await _call(
        executor,
        colony_name="ok_name",
        task="t",
        skill_path=str(folder),
    )
    assert "error" in payload
    assert "frontmatter" in payload["error"]
    assert len(patched_fork) == 0


@pytest.mark.asyncio
async def test_skill_md_missing_description_rejected(
    tmp_path, patched_home, patched_fork
) -> None:
    executor, _ = _make_executor()
    folder = tmp_path / "no-description"
    folder.mkdir()
    (folder / "SKILL.md").write_text(
        "---\nname: no-description\n---\n\nbody\n",
        encoding="utf-8",
    )
    payload = await _call(
        executor,
        colony_name="ok_name",
        task="t",
        skill_path=str(folder),
    )
    assert "error" in payload
    assert "description" in payload["error"]
    assert len(patched_fork) == 0


@pytest.mark.asyncio
async def test_directory_name_mismatch_with_frontmatter_rejected(
    tmp_path, patched_home, patched_fork
) -> None:
    executor, _ = _make_executor()
    folder = tmp_path / "wrong-dir-name"
    folder.mkdir()
    (folder / "SKILL.md").write_text(
        '---\nname: correct-name\ndescription: "d"\n---\n\nbody\n',
        encoding="utf-8",
    )
    payload = await _call(
        executor,
        colony_name="ok_name",
        task="t",
        skill_path=str(folder),
    )
    assert "error" in payload
    assert "does not match" in payload["error"]
    assert len(patched_fork) == 0


@pytest.mark.asyncio
async def test_invalid_colony_name_rejected(tmp_path, patched_home, patched_fork) -> None:
    executor, _ = _make_executor()
    skill_src = _write_skill(
        tmp_path, dir_name="valid-skill", fm_name="valid-skill"
    )
    payload = await _call(
        executor,
        colony_name="NotValid-Colony",
        task="t",
        skill_path=str(skill_src),
    )
    assert "error" in payload
    assert "colony_name" in payload["error"]
    assert len(patched_fork) == 0


@pytest.mark.asyncio
async def test_fork_failure_keeps_installed_skill(
    tmp_path, patched_home, monkeypatch
) -> None:
    """If the fork raises, the installed skill stays under ~/.hive/skills/."""

    async def _failing_fork(**kwargs):
        raise RuntimeError("simulated fork crash")

    monkeypatch.setattr(
        "framework.server.routes_execution.fork_session_into_colony",
        _failing_fork,
    )

    executor, _ = _make_executor()
    skill_src = _write_skill(
        tmp_path, dir_name="durable-skill", fm_name="durable-skill"
    )

    payload = await _call(
        executor,
        colony_name="will_fail",
        task="t",
        skill_path=str(skill_src),
    )
    assert "error" in payload
    assert "fork failed" in payload["error"]
    assert "skill_installed" in payload
    installed = patched_home / ".hive" / "skills" / "durable-skill" / "SKILL.md"
    assert installed.exists()
    assert "hint" in payload
