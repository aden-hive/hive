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
def patched_fork(tmp_path, monkeypatch):
    """Stub out fork_session_into_colony so we don't need a real queen.

    The stub creates a real colony directory under tmp_path and writes
    a minimal ``worker.json`` so the create_colony tool can install the
    skill colony-scoped and patch worker.json::skill_dirs.
    """
    calls: list[dict] = []
    fake_colonies_root = tmp_path / "fake_colonies"
    fake_colonies_root.mkdir(parents=True, exist_ok=True)

    async def _stub_fork(*, session: Any, colony_name: str, task: str) -> dict:
        calls.append({"session": session, "colony_name": colony_name, "task": task})
        colony_dir = fake_colonies_root / colony_name
        colony_dir.mkdir(parents=True, exist_ok=True)
        # Minimal worker.json with an existing skill_dirs list so the
        # patch step has something to mutate.
        worker_json = colony_dir / "worker.json"
        if not worker_json.exists():
            worker_json.write_text(
                json.dumps({"name": "worker", "skill_dirs": []}),
                encoding="utf-8",
            )
        return {
            "colony_path": str(colony_dir),
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
async def test_happy_path_installs_skill_colony_scoped(
    tmp_path: Path, patched_home: Path, patched_fork: list[dict]
) -> None:
    """Skill authored in a scratch dir is installed under {colony}/skills/{name}/.

    The user-global ~/.hive/skills/ path must NOT be touched — that
    would leak the skill to every other agent on the machine.
    """
    executor, session = _make_executor()

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
        ),
    )

    payload = await _call(
        executor,
        colony_name="honeycomb_research",
        task="Build the daily report.",
        skill_path=str(skill_src),
    )

    assert payload.get("status") == "created", f"Tool error: {payload}"
    assert payload["colony_name"] == "honeycomb_research"
    assert payload["skill_name"] == "honeycomb-api-protocol"
    assert payload["skill_scope"] == "colony"

    # Skill landed under {colony}/skills/, NOT under ~/.hive/skills/
    colony_dir = tmp_path / "fake_colonies" / "honeycomb_research"
    installed_skill_md = (
        colony_dir / "skills" / "honeycomb-api-protocol" / "SKILL.md"
    )
    assert installed_skill_md.exists()
    assert "HoneyComb API Operational Protocol" in installed_skill_md.read_text(
        encoding="utf-8"
    )

    # Critically: ~/.hive/skills/ is NOT touched
    user_global_path = (
        patched_home / ".hive" / "skills" / "honeycomb-api-protocol"
    )
    assert not user_global_path.exists(), (
        "Skill leaked into the user-global ~/.hive/skills/ — should be "
        "colony-scoped only"
    )

    # worker.json::skill_dirs is patched to include the colony skills dir
    worker_json = json.loads(
        (colony_dir / "worker.json").read_text(encoding="utf-8")
    )
    skill_dirs = worker_json.get("skill_dirs", [])
    assert str(colony_dir / "skills") in skill_dirs

    # Fork was called with the right args
    assert len(patched_fork) == 1
    assert patched_fork[0]["colony_name"] == "honeycomb_research"
    assert patched_fork[0]["session"] is session


@pytest.mark.asyncio
async def test_happy_path_emits_colony_created_event(
    tmp_path: Path, patched_home: Path, patched_fork: list[dict]
) -> None:
    """Successful create_colony must publish a COLONY_CREATED event."""
    from framework.host.event_bus import AgentEvent, EventType

    executor, session = _make_executor()

    received: list[AgentEvent] = []

    async def _on_colony_created(event: AgentEvent) -> None:
        received.append(event)

    session.event_bus.subscribe(
        event_types=[EventType.COLONY_CREATED],
        handler=_on_colony_created,
    )

    skill_src = _write_skill(
        tmp_path / "scratch", dir_name="my-skill", fm_name="my-skill"
    )

    payload = await _call(
        executor,
        colony_name="event_check",
        task="t",
        skill_path=str(skill_src),
    )
    assert payload.get("status") == "created", payload
    assert len(received) == 1
    ev = received[0]
    assert ev.type == EventType.COLONY_CREATED
    assert ev.data.get("colony_name") == "event_check"
    assert ev.data.get("skill_name") == "my-skill"
    assert ev.data.get("is_new") is True
    # The event payload's skill_installed must point to the colony-scoped
    # location, not ~/.hive/skills/
    skill_installed = ev.data.get("skill_installed", "")
    assert "fake_colonies/event_check/skills/my-skill" in skill_installed


@pytest.mark.asyncio
async def test_worker_json_skill_dirs_prepends_for_precedence(
    tmp_path: Path, patched_home: Path, monkeypatch
) -> None:
    """Existing skill_dirs entries are preserved; the colony dir is prepended."""
    calls: list[dict] = []
    fake_colonies_root = tmp_path / "fake_colonies"
    fake_colonies_root.mkdir(parents=True, exist_ok=True)

    async def _stub_fork(*, session: Any, colony_name: str, task: str) -> dict:
        calls.append({"colony_name": colony_name})
        colony_dir = fake_colonies_root / colony_name
        colony_dir.mkdir(parents=True, exist_ok=True)
        # Pre-existing skill dirs the queen had at fork time
        (colony_dir / "worker.json").write_text(
            json.dumps(
                {
                    "name": "worker",
                    "skill_dirs": [
                        "/framework/defaults",
                        "/project/.hive/skills",
                    ],
                }
            ),
            encoding="utf-8",
        )
        return {
            "colony_path": str(colony_dir),
            "colony_name": colony_name,
            "queen_session_id": "sid",
            "is_new": True,
        }

    monkeypatch.setattr(
        "framework.server.routes_execution.fork_session_into_colony",
        _stub_fork,
    )

    executor, _ = _make_executor()
    skill_src = _write_skill(
        tmp_path / "scratch", dir_name="precedence-skill", fm_name="precedence-skill"
    )
    payload = await _call(
        executor,
        colony_name="precedence_check",
        task="t",
        skill_path=str(skill_src),
    )
    assert payload.get("status") == "created", payload

    colony_dir = fake_colonies_root / "precedence_check"
    worker_json = json.loads(
        (colony_dir / "worker.json").read_text(encoding="utf-8")
    )
    skill_dirs = worker_json["skill_dirs"]
    # Colony dir prepended (highest precedence) and existing entries
    # preserved in order after it.
    assert skill_dirs[0] == str(colony_dir / "skills")
    assert "/framework/defaults" in skill_dirs
    assert "/project/.hive/skills" in skill_dirs


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
async def test_fork_failure_returns_clean_error(
    tmp_path, patched_home, monkeypatch
) -> None:
    """If the fork raises, no skill is installed and the error is reported.

    The new flow is validate → fork → install, so a fork failure means
    nothing has been installed yet — neither colony-scoped nor user-global.
    The error message must say so and the user-global ~/.hive/skills/
    must remain untouched.
    """

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
    assert "hint" in payload

    # Critical: no leakage to ~/.hive/skills/ (the old behavior installed
    # there before fork — that's now gone)
    user_global = patched_home / ".hive" / "skills" / "durable-skill"
    assert not user_global.exists()
