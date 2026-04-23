"""Wiring smoke test for the queen → fork → colony flow.

Validates the on-disk artifacts produced by ``handle_colony_spawn`` and
that ``create_session_with_worker_colony`` resolves the colony's forked
session ID from ``metadata.json`` rather than spinning up a fresh ID.

These tests do NOT exercise the LLM or the queen identity hook -- they
construct a Session object with the minimum state ``handle_colony_spawn``
needs and run everything against a temp directory.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp.test_utils import TestClient, TestServer

from framework.agent_loop.internals.types import LoopConfig
from framework.server.app import create_app
from framework.server.session_manager import Session, _queen_session_dir

# Modules that import HIVE_HOME / QUEENS_DIR / COLONIES_DIR / MEMORIES_DIR /
# HIVE_CONFIG_FILE at import time and need their bindings rewritten when we
# redirect ~/.hive to a temp directory. Patching Path.home alone is NOT
# sufficient -- these constants are captured once at module import.
_HIVE_PATH_CONSUMERS = (
    "framework.config",
    "framework.server.session_manager",
    "framework.server.queen_orchestrator",
    "framework.server.routes_queens",
    "framework.server.app",
    "framework.agents.discovery",
    "framework.agents.queen.queen_profiles",
    "framework.tools.queen_lifecycle_tools",
    "framework.storage.migrate_v2",
    "framework.loader.cli",
)

_HIVE_PATH_NAMES = (
    ("HIVE_HOME", lambda h: h),
    ("QUEENS_DIR", lambda h: h / "agents" / "queens"),
    ("COLONIES_DIR", lambda h: h / "colonies"),
    ("MEMORIES_DIR", lambda h: h / "memories"),
    ("HIVE_CONFIG_FILE", lambda h: h / "configuration.json"),
)


def _isolate_hive_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect ~/.hive to ``tmp_path/.hive`` for this test.

    Patches ``Path.home()`` and every module-level binding of
    ``HIVE_HOME``/``QUEENS_DIR``/``COLONIES_DIR``/``MEMORIES_DIR``/
    ``HIVE_CONFIG_FILE`` that was captured at import time. Without this,
    tests that exercise the fork handler leak real session directories
    into the developer's actual ``~/.hive/agents/queens/`` tree.
    """
    fake_home_root = tmp_path
    fake_hive = fake_home_root / ".hive"
    fake_hive.mkdir(exist_ok=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home_root))
    for mod_name in _HIVE_PATH_CONSUMERS:
        try:
            mod = importlib.import_module(mod_name)
        except ImportError:
            continue
        for attr_name, builder in _HIVE_PATH_NAMES:
            if hasattr(mod, attr_name):
                monkeypatch.setattr(mod, attr_name, builder(fake_hive))
    return fake_hive


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_fake_queen_session(
    home: Path,
    *,
    queen_name: str,
    session_id: str,
) -> Path:
    """Create a fake queen session directory with conversations and meta.json."""
    queen_dir = home / ".hive" / "agents" / "queens" / queen_name / "sessions" / session_id
    (queen_dir / "conversations" / "parts").mkdir(parents=True)
    (queen_dir / "data").mkdir()

    # Two fake conversation parts so we can verify they get copied
    parts = queen_dir / "conversations" / "parts"
    (parts / "0000000000.json").write_text(
        json.dumps({"seq": 0, "role": "user", "content": "trade honeycomb"}),
        encoding="utf-8",
    )
    (parts / "0000000001.json").write_text(
        json.dumps({"seq": 1, "role": "assistant", "content": "on it"}),
        encoding="utf-8",
    )

    # Conversation cursor + meta
    (queen_dir / "conversations" / "cursor.json").write_text("{}", encoding="utf-8")
    (queen_dir / "conversations" / "meta.json").write_text("{}", encoding="utf-8")

    # Session meta.json (this is the queen-session meta, distinct from convs/meta.json)
    (queen_dir / "meta.json").write_text(
        json.dumps({"created_at": 1, "queen_id": queen_name}),
        encoding="utf-8",
    )

    # Empty events log
    (queen_dir / "events.jsonl").write_text("", encoding="utf-8")

    return queen_dir


def _make_session_with_queen_state(
    *,
    session_id: str,
    queen_name: str,
    queen_dir: Path,
) -> Session:
    """Construct a Session pre-populated with the state colony-spawn reads."""
    bus = MagicMock()
    bus.publish = AsyncMock()

    # Fake queen_loop with the attributes the spawn handler reads
    fake_loop = SimpleNamespace(
        _last_ctx=SimpleNamespace(
            available_tools=[
                SimpleNamespace(name="read_file"),
                SimpleNamespace(name="search_files"),
            ],
            skills_catalog_prompt="<skills/>",
            protocols_prompt="<protocols/>",
            skill_dirs=["/fake/skills"],
        ),
        _config=LoopConfig(
            max_iterations=42,
            max_tool_calls_per_turn=7,
            max_context_tokens=99_000,
            max_tool_result_chars=2048,
        ),
        _conversation_store=None,
    )
    queen_executor = SimpleNamespace(node_registry={"queen": fake_loop})

    # Fake phase_state with the attributes the spawn handler reads
    phase_state = SimpleNamespace(
        phase="planning",
        queen_id=queen_name,
        queen_identity_prompt="You are Charlotte, head of finance.",
        _cached_global_recall_block="",
        get_current_prompt=lambda: "you are the queen",
        global_memory_dir=None,
        queen_memory_dir=None,
    )

    session = Session(
        id=session_id,
        event_bus=bus,
        llm=MagicMock(),
        loaded_at=0.0,
        queen_executor=queen_executor,
        queen_dir=queen_dir,
        queen_name=queen_name,
        phase_state=phase_state,
    )
    return session


# ---------------------------------------------------------------------------
# 1. AgentLoader skips metadata.json when picking a worker config
# ---------------------------------------------------------------------------


def test_agent_loader_picks_worker_json_not_metadata_json(tmp_path):
    """AgentLoader.load must select worker.json from a colony, not metadata.json.

    Regression: ``metadata.json`` sorts before ``worker.json`` alphabetically;
    if it isn't excluded, the loader treats colony provenance as a worker spec
    and the worker spawns under the wrong storage path with no goal/tools.
    """
    from framework.loader.agent_loader import AgentLoader

    colony_dir = tmp_path / "colonies" / "honeycomb"
    colony_dir.mkdir(parents=True)
    (colony_dir / "data").mkdir()

    # Colony provenance (must NOT be picked)
    (colony_dir / "metadata.json").write_text(
        json.dumps(
            {
                "colony_name": "honeycomb",
                "queen_name": "queen_finance_fundraising",
                "queen_session_id": "session_xxx",
                "workers": {"worker": {"task": "trade"}},
            }
        ),
        encoding="utf-8",
    )

    # Real worker config
    (colony_dir / "worker.json").write_text(
        json.dumps(
            {
                "name": "worker",
                "version": "1.0.0",
                "description": "trader",
                "goal": {"description": "trade honeycomb", "success_criteria": [], "constraints": []},
                "system_prompt": "be a careful trader",
                "tools": ["read_file", "search_files"],
                "loop_config": {"max_iterations": 50},
            }
        ),
        encoding="utf-8",
    )

    runner = AgentLoader.load(
        colony_dir,
        interactive=False,
        skip_credential_validation=True,
    )

    # Picked the right config: name comes from worker.json
    assert runner.graph.nodes[0].id == "worker"
    assert runner.goal.description == "trade honeycomb"
    assert "read_file" in runner.graph.nodes[0].tools


# ---------------------------------------------------------------------------
# 2. handle_colony_spawn produces the correct on-disk artifacts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_colony_spawn_creates_correct_artifacts(tmp_path, monkeypatch):
    """End-to-end POST /api/sessions/{id}/colony-spawn against an in-process app.

    Validates the full set of artifacts produced by the spawn handler,
    catching the bugs we hit yesterday:
      - queen_name in metadata.json must be the actual queen profile, not "default"
      - queen_session_id in metadata.json must point to the duplicated dir
      - duplicated session dir must live under the correct queen identity
      - duplicated session must be flagged colony_fork=true
      - worker.json must contain the queen state snapshot
      - worker storage must receive the queen conversations
      - source queen session meta must be linked back to the colony
    """
    _isolate_hive_home(tmp_path, monkeypatch)

    queen_name = "queen_finance_fundraising"
    source_session_id = "session_20260410_120000_aaaaaaaa"

    # Pre-create a fake queen session on disk
    source_queen_dir = _make_fake_queen_session(
        tmp_path,
        queen_name=queen_name,
        session_id=source_session_id,
    )

    # Build the in-process aiohttp app and inject our fake session
    app = create_app()
    manager = app["manager"]
    session = _make_session_with_queen_state(
        session_id=source_session_id,
        queen_name=queen_name,
        queen_dir=source_queen_dir,
    )
    manager._sessions[session.id] = session

    async with TestClient(TestServer(app)) as client:
        resp = await client.post(
            f"/api/sessions/{source_session_id}/colony-spawn",
            json={"colony_name": "honeycomb", "task": "trade carefully"},
        )
        assert resp.status == 200, await resp.text()
        body = await resp.json()

        # fork_session_into_colony schedules the compaction + worker-storage
        # copy onto _BACKGROUND_FORK_TASKS and returns. In prod the colony-
        # open path blocks on compaction_status.await_completion; the test
        # skips that step, so drain the bg tasks here before asserting on
        # the artifacts they produce (otherwise the worker-storage check is
        # a race that flakes under CI load).
        from framework.server.routes_execution import _BACKGROUND_FORK_TASKS

        if _BACKGROUND_FORK_TASKS:
            await asyncio.gather(*list(_BACKGROUND_FORK_TASKS), return_exceptions=True)

    colony_session_id = body["queen_session_id"]
    assert body["colony_name"] == "honeycomb"
    assert body["is_new"] is True
    assert colony_session_id != source_session_id

    # ── colony_dir layout ──────────────────────────────────────────
    colony_dir = tmp_path / ".hive" / "colonies" / "honeycomb"
    assert colony_dir.is_dir()
    assert (colony_dir / "data").is_dir()
    assert (colony_dir / "worker.json").is_file()
    assert (colony_dir / "metadata.json").is_file()

    # ── metadata.json contents ─────────────────────────────────────
    metadata = json.loads((colony_dir / "metadata.json").read_text())
    assert metadata["colony_name"] == "honeycomb"
    assert metadata["queen_name"] == queen_name, (
        f"queen_name should be the actual queen profile, got {metadata['queen_name']!r}"
    )
    assert metadata["queen_session_id"] == colony_session_id
    assert metadata["source_session_id"] == source_session_id
    assert "worker" in metadata["workers"]
    assert metadata["workers"]["worker"]["task"] == "trade carefully"

    # ── worker.json contents ───────────────────────────────────────
    worker_meta = json.loads((colony_dir / "worker.json").read_text())
    assert worker_meta["name"] == "worker"
    assert worker_meta["queen_id"] == queen_name
    assert worker_meta["queen_phase"] == "planning"
    assert worker_meta["spawned_from"] == source_session_id
    assert worker_meta["goal"]["description"] == "trade carefully"
    # The worker system_prompt is a FOCUSED task brief, NOT the queen's
    # persona prompt. The queen's identity must not leak into the worker.
    assert "focused worker" in worker_meta["system_prompt"]
    assert "trade carefully" in worker_meta["system_prompt"]
    assert "Charlotte" not in worker_meta["system_prompt"]
    # identity_prompt and memory_prompt must be empty -- the worker is
    # not the queen and must not inherit her persona or global memory.
    assert worker_meta["identity_prompt"] == ""
    assert worker_meta["memory_prompt"] == ""
    assert worker_meta["tools"] == ["read_file", "search_files"]
    assert worker_meta["skills_catalog_prompt"] == "<skills/>"
    assert worker_meta["protocols_prompt"] == "<protocols/>"
    assert worker_meta["loop_config"]["max_iterations"] == 42
    assert worker_meta["loop_config"]["max_tool_calls_per_turn"] == 7

    # ── duplicated queen session dir ──────────────────────────────
    dest_queen_dir = _queen_session_dir(colony_session_id, queen_name)
    assert dest_queen_dir.is_dir(), f"Forked session dir not under {queen_name}/, got {dest_queen_dir}"

    # Conversations were copied
    assert (dest_queen_dir / "conversations" / "parts" / "0000000000.json").is_file()
    assert (dest_queen_dir / "conversations" / "parts" / "0000000001.json").is_file()

    # Forked meta.json carries the colony_fork flag and links to the colony
    dest_meta = json.loads((dest_queen_dir / "meta.json").read_text())
    assert dest_meta["colony_fork"] is True
    assert dest_meta["forked_from"] == source_session_id
    assert dest_meta["queen_id"] == queen_name
    assert dest_meta["agent_path"] == str(colony_dir)
    assert dest_meta["agent_name"] == "Honeycomb"

    # ── worker storage receives queen conversations ───────────────
    worker_storage_convs = tmp_path / ".hive" / "agents" / "honeycomb" / "worker" / "conversations"
    assert worker_storage_convs.is_dir()
    assert (worker_storage_convs / "parts" / "0000000000.json").is_file()

    # ── source queen session updated with agent_path ──────────────
    source_meta = json.loads((source_queen_dir / "meta.json").read_text())
    assert source_meta["agent_path"] == str(colony_dir)
    assert source_meta["agent_name"] == "Honeycomb"


# ---------------------------------------------------------------------------
# 3. create_session_with_worker_colony resolves the forked session ID from
#    metadata.json (not whatever the caller passed in)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_session_with_worker_colony_uses_forked_session_id(tmp_path, monkeypatch):
    """When a colony is loaded, its metadata.json's queen_session_id wins.

    Regression: returning to a colony was loading the SOURCE queen session
    instead of the forked one because the frontend's history scan found the
    source first. The backend now overrides ``queen_resume_from`` with the
    colony's designated session ID.
    """
    _isolate_hive_home(tmp_path, monkeypatch)

    from framework.server.session_manager import SessionManager

    queen_name = "queen_finance_fundraising"
    source_id = "session_20260410_120000_aaaaaaaa"
    forked_id = "session_20260410_130000_bbbbbbbb"

    # Pre-create the forked queen session that the colony points at
    _make_fake_queen_session(tmp_path, queen_name=queen_name, session_id=forked_id)
    # Also create a source session (the one we don't want to be picked)
    _make_fake_queen_session(tmp_path, queen_name=queen_name, session_id=source_id)

    # Build the colony dir with metadata pointing at the forked session
    colony_dir = tmp_path / ".hive" / "colonies" / "honeycomb"
    colony_dir.mkdir(parents=True)
    (colony_dir / "data").mkdir()
    (colony_dir / "metadata.json").write_text(
        json.dumps(
            {
                "colony_name": "honeycomb",
                "queen_name": queen_name,
                "queen_session_id": forked_id,
                "source_session_id": source_id,
                "workers": {"worker": {"task": "trade"}},
            }
        ),
        encoding="utf-8",
    )
    (colony_dir / "worker.json").write_text(
        json.dumps(
            {
                "name": "worker",
                "version": "1.0.0",
                "description": "trader",
                "goal": {"description": "trade", "success_criteria": [], "constraints": []},
                "system_prompt": "be a trader",
                "tools": [],
                "loop_config": {},
            }
        ),
        encoding="utf-8",
    )

    manager = SessionManager(model="claude-haiku-4-5-20251001")

    # Stub out the heavy bits: we only care about session-id resolution.
    captured: dict = {}

    async def fake_load_worker_core(self, session, agent_path, *, colony_id=None, model=None):
        session.colony_id = colony_id or Path(agent_path).name
        session.worker_path = Path(agent_path)
        session.colony_runtime = MagicMock()
        session.worker_info = SimpleNamespace(name="worker")

    async def fake_start_queen(self, session, **kwargs):
        captured["session_id"] = session.id
        captured["queen_resume_from"] = session.queen_resume_from
        captured["queen_name"] = session.queen_name
        session.queen_executor = SimpleNamespace(node_registry={"queen": MagicMock()})

    async def fake_restore_active_triggers(self, session, session_id):
        return None

    monkeypatch.setattr(SessionManager, "_load_worker_core", fake_load_worker_core)
    monkeypatch.setattr(SessionManager, "_start_queen", fake_start_queen)
    monkeypatch.setattr(SessionManager, "_restore_active_triggers", fake_restore_active_triggers)

    # Caller passes the SOURCE session id (mimicking the frontend's history scan)
    session = await manager.create_session_with_worker_colony(
        agent_path=colony_dir,
        queen_resume_from=source_id,
    )

    # The colony's forked session ID should win, not the caller's source ID
    assert captured["queen_resume_from"] == forked_id, (
        f"Expected forked id {forked_id}, got {captured['queen_resume_from']}"
    )
    assert session.id == forked_id, f"Live session ID should match forked session, got {session.id}"
    assert captured["queen_name"] == queen_name
