"""Tests for the queen-side ``create_colony`` tool.

Contract (atomic inline-skill flow):

The queen calls ``create_colony(colony_name, task, skill_name,
skill_description, skill_body, skill_files?, tasks?)`` in a single
call. The tool materializes ``~/.hive/skills/{skill_name}/`` from the
inline content (writing SKILL.md and any supporting files), then forks
the queen session into a colony. Reusing an existing skill name simply
replaces the old skill — the queen owns her skill namespace.

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
    result = executor(ToolUse(id="tu_create_colony", name="create_colony", input=inputs))
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

    async def _stub_fork(
        *,
        session: Any,
        colony_name: str,
        task: str,
        tasks: list[dict] | None = None,
    ) -> dict:
        calls.append(
            {
                "session": session,
                "colony_name": colony_name,
                "task": task,
                "tasks": tasks,
            }
        )
        return {
            "colony_path": f"/tmp/fake_colonies/{colony_name}",
            "colony_name": colony_name,
            "queen_session_id": "session_fake_fork_id",
            "is_new": True,
            "db_path": f"/tmp/fake_colonies/{colony_name}/data/progress.db",
            "task_ids": [],
        }

    monkeypatch.setattr(
        "framework.server.routes_execution.fork_session_into_colony",
        _stub_fork,
    )
    return calls


_DEFAULT_BODY = (
    "## Operational Protocol\n\n"
    "Auth: Bearer token from ~/.hive/credentials/honeycomb.json.\n"
    "Pagination: ?page=1&page_size=50 (max 50 per page).\n"
)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_emits_colony_created_event(
    patched_home: Path, patched_fork: list[dict]
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

    payload = await _call(
        executor,
        colony_name="event_check",
        task="t",
        skill_name="my-skill",
        skill_description="My test skill for event-check happy path.",
        skill_body=_DEFAULT_BODY,
    )
    assert payload.get("status") == "created", payload
    assert payload["skill_replaced"] is False
    assert len(received) == 1
    ev = received[0]
    assert ev.type == EventType.COLONY_CREATED
    assert ev.data.get("colony_name") == "event_check"
    assert ev.data.get("skill_name") == "my-skill"
    assert ev.data.get("skill_replaced") is False
    assert ev.data.get("is_new") is True


@pytest.mark.asyncio
async def test_happy_path_materializes_skill_under_home(
    patched_home: Path, patched_fork: list[dict]
) -> None:
    """Inline skill content is written to ~/.hive/skills/{name}/."""
    executor, session = _make_executor()

    description = (
        "How to query the HoneyComb staging API for ticker, pool, "
        "and trade data. Covers auth, pagination, pool detail shape."
    )
    body = (
        "## HoneyComb API Operational Protocol\n\n"
        "Auth: Bearer token from ~/.hive/credentials/honeycomb.json.\n"
        "Pagination: ?page=1&page_size=50 (max 50 per page).\n"
        "Endpoints:\n"
        "- /api/ticker — list tickers\n"
        "- /api/ticker/{id} — pool detail\n"
    )

    payload = await _call(
        executor,
        colony_name="honeycomb_research",
        task=(
            "Build a daily honeycomb market report covering top gainers, "
            "losers, volume leaders, and category breakdowns."
        ),
        skill_name="honeycomb-api-protocol",
        skill_description=description,
        skill_body=body,
    )

    assert payload.get("status") == "created", f"Tool error: {payload}"
    assert payload["colony_name"] == "honeycomb_research"
    assert payload["skill_name"] == "honeycomb-api-protocol"
    assert payload["skill_replaced"] is False

    installed = patched_home / ".hive" / "skills" / "honeycomb-api-protocol" / "SKILL.md"
    assert installed.exists()
    text = installed.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    assert "name: honeycomb-api-protocol" in text
    assert f"description: {description}" in text
    assert "HoneyComb API Operational Protocol" in text

    # Fork was called with the right args
    assert len(patched_fork) == 1
    assert patched_fork[0]["colony_name"] == "honeycomb_research"
    assert "honeycomb market report" in patched_fork[0]["task"]
    assert patched_fork[0]["session"] is session


@pytest.mark.asyncio
async def test_skill_files_are_written_alongside_skill_md(
    patched_home: Path, patched_fork: list[dict]
) -> None:
    """skill_files entries land at the right relative paths."""
    executor, _ = _make_executor()

    payload = await _call(
        executor,
        colony_name="fancy_skill",
        task="t",
        skill_name="fancy-skill",
        skill_description="Has supporting scripts and references.",
        skill_body=_DEFAULT_BODY,
        skill_files=[
            {"path": "scripts/run.sh", "content": "#!/bin/sh\necho hi\n"},
            {"path": "references/shapes.md", "content": "# Shapes\nfoo\n"},
        ],
    )
    assert payload.get("status") == "created", payload

    skill_dir = patched_home / ".hive" / "skills" / "fancy-skill"
    assert (skill_dir / "SKILL.md").exists()
    assert (skill_dir / "scripts" / "run.sh").read_text() == "#!/bin/sh\necho hi\n"
    assert (skill_dir / "references" / "shapes.md").read_text() == "# Shapes\nfoo\n"


@pytest.mark.asyncio
async def test_existing_skill_is_replaced(
    patched_home: Path, patched_fork: list[dict]
) -> None:
    """Reusing a skill_name replaces the old skill with fresh content."""
    executor, _ = _make_executor()

    skill_root = patched_home / ".hive" / "skills" / "x-job-market-replier"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "---\nname: x-job-market-replier\ndescription: stale\n---\n\nold body\n",
        encoding="utf-8",
    )
    (skill_root / "stale.txt").write_text("leftover from prior version", encoding="utf-8")

    payload = await _call(
        executor,
        colony_name="replier_colony",
        task="t",
        skill_name="x-job-market-replier",
        skill_description="Reply to job-market posts on X.",
        skill_body="## New procedure\nUse this instead.\n",
    )

    assert payload.get("status") == "created", payload
    assert payload["skill_replaced"] is True

    fresh = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    assert "stale" not in fresh
    assert "New procedure" in fresh
    # Old sidecar files from the prior version must be gone.
    assert not (skill_root / "stale.txt").exists()


# ---------------------------------------------------------------------------
# Validation failures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_skill_name_rejected(patched_home, patched_fork) -> None:
    executor, _ = _make_executor()
    payload = await _call(
        executor,
        colony_name="ok_name",
        task="t",
        skill_name="",
        skill_description="desc",
        skill_body=_DEFAULT_BODY,
    )
    assert "error" in payload
    assert "skill_name" in payload["error"]
    assert len(patched_fork) == 0


@pytest.mark.asyncio
async def test_invalid_skill_name_characters_rejected(patched_home, patched_fork) -> None:
    executor, _ = _make_executor()
    payload = await _call(
        executor,
        colony_name="ok_name",
        task="t",
        skill_name="Bad_Name",
        skill_description="desc",
        skill_body=_DEFAULT_BODY,
    )
    assert "error" in payload
    assert "[a-z0-9-]" in payload["error"]
    assert len(patched_fork) == 0


@pytest.mark.asyncio
async def test_skill_name_with_double_hyphen_rejected(patched_home, patched_fork) -> None:
    executor, _ = _make_executor()
    payload = await _call(
        executor,
        colony_name="ok_name",
        task="t",
        skill_name="bad--name",
        skill_description="desc",
        skill_body=_DEFAULT_BODY,
    )
    assert "error" in payload
    assert "hyphen" in payload["error"]
    assert len(patched_fork) == 0


@pytest.mark.asyncio
async def test_missing_skill_description_rejected(patched_home, patched_fork) -> None:
    executor, _ = _make_executor()
    payload = await _call(
        executor,
        colony_name="ok_name",
        task="t",
        skill_name="ok-skill",
        skill_description="",
        skill_body=_DEFAULT_BODY,
    )
    assert "error" in payload
    assert "skill_description" in payload["error"]
    assert len(patched_fork) == 0


@pytest.mark.asyncio
async def test_multiline_description_rejected(patched_home, patched_fork) -> None:
    executor, _ = _make_executor()
    payload = await _call(
        executor,
        colony_name="ok_name",
        task="t",
        skill_name="ok-skill",
        skill_description="line one\nline two",
        skill_body=_DEFAULT_BODY,
    )
    assert "error" in payload
    assert "single line" in payload["error"]
    assert len(patched_fork) == 0


@pytest.mark.asyncio
async def test_empty_skill_body_rejected(patched_home, patched_fork) -> None:
    executor, _ = _make_executor()
    payload = await _call(
        executor,
        colony_name="ok_name",
        task="t",
        skill_name="ok-skill",
        skill_description="desc",
        skill_body="   \n  ",
    )
    assert "error" in payload
    assert "skill_body" in payload["error"]
    assert len(patched_fork) == 0


@pytest.mark.asyncio
async def test_invalid_colony_name_rejected(patched_home, patched_fork) -> None:
    executor, _ = _make_executor()
    payload = await _call(
        executor,
        colony_name="NotValid-Colony",
        task="t",
        skill_name="valid-skill",
        skill_description="desc",
        skill_body=_DEFAULT_BODY,
    )
    assert "error" in payload
    assert "colony_name" in payload["error"]
    assert len(patched_fork) == 0


@pytest.mark.asyncio
async def test_skill_files_reject_absolute_path(patched_home, patched_fork) -> None:
    executor, _ = _make_executor()
    payload = await _call(
        executor,
        colony_name="ok_name",
        task="t",
        skill_name="ok-skill",
        skill_description="desc",
        skill_body=_DEFAULT_BODY,
        skill_files=[{"path": "/etc/passwd", "content": "evil"}],
    )
    assert "error" in payload
    assert "relative" in payload["error"]
    assert len(patched_fork) == 0


@pytest.mark.asyncio
async def test_skill_files_reject_parent_traversal(patched_home, patched_fork) -> None:
    executor, _ = _make_executor()
    payload = await _call(
        executor,
        colony_name="ok_name",
        task="t",
        skill_name="ok-skill",
        skill_description="desc",
        skill_body=_DEFAULT_BODY,
        skill_files=[{"path": "../escape.txt", "content": "evil"}],
    )
    assert "error" in payload
    assert "relative" in payload["error"]
    assert len(patched_fork) == 0


@pytest.mark.asyncio
async def test_skill_files_reject_skill_md_override(patched_home, patched_fork) -> None:
    executor, _ = _make_executor()
    payload = await _call(
        executor,
        colony_name="ok_name",
        task="t",
        skill_name="ok-skill",
        skill_description="desc",
        skill_body=_DEFAULT_BODY,
        skill_files=[{"path": "SKILL.md", "content": "sneaky"}],
    )
    assert "error" in payload
    assert "SKILL.md" in payload["error"]
    assert len(patched_fork) == 0


@pytest.mark.asyncio
async def test_fork_failure_keeps_materialized_skill(
    patched_home, monkeypatch
) -> None:
    """If the fork raises, the materialized skill stays under ~/.hive/skills/."""

    async def _failing_fork(**kwargs):
        raise RuntimeError("simulated fork crash")

    monkeypatch.setattr(
        "framework.server.routes_execution.fork_session_into_colony",
        _failing_fork,
    )

    executor, _ = _make_executor()

    payload = await _call(
        executor,
        colony_name="will_fail",
        task="t",
        skill_name="durable-skill",
        skill_description="desc",
        skill_body=_DEFAULT_BODY,
    )
    assert "error" in payload
    assert "fork failed" in payload["error"]
    assert "skill_installed" in payload
    installed = patched_home / ".hive" / "skills" / "durable-skill" / "SKILL.md"
    assert installed.exists()
    assert "hint" in payload
