"""Phase 2 wiring test: SessionManager._start_unified_colony_runtime.

Verifies that after a queen-mode session is started, ``session.colony``
is a real, running ``ColonyRuntime`` sharing the queen's event bus and
LLM, and that workers spawned through it land on disk under
``{queen_dir}/workers/{worker_id}/`` (NOT in the process CWD).

We bypass ``create_queen`` by stashing the tools directly on the session
and calling the helper, so the test is decoupled from queen orchestration.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from framework.host.colony_runtime import ColonyRuntime
from framework.host.event_bus import EventBus
from framework.server.session_manager import Session, SessionManager


@pytest.mark.asyncio
async def test_start_unified_colony_runtime_creates_real_colony(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The helper builds a ColonyRuntime, starts it, and stashes it on session.colony."""
    bus = EventBus()
    session_llm = object()  # sentinel — not invoked in this test
    session = Session(
        id="session_phase2_test",
        event_bus=bus,
        llm=session_llm,
        loaded_at=0.0,
    )
    # _start_unified_colony_runtime reads these — usually create_queen
    # stashes them, but here we set them directly.
    session._queen_tools = []  # type: ignore[attr-defined]
    session._queen_tool_executor = None  # type: ignore[attr-defined]

    queen_dir = tmp_path / "queens" / "default" / "sessions" / session.id
    queen_dir.mkdir(parents=True)

    manager = SessionManager()
    # Pin build_worker_llm to None so the test stays deterministic
    # regardless of the dev machine's ~/.hive/configuration.json.
    monkeypatch.setattr(manager, "build_worker_llm", lambda: None)
    await manager._start_unified_colony_runtime(session, queen_dir)

    try:
        assert session.colony is not None
        assert isinstance(session.colony, ColonyRuntime)
        assert session.colony.is_running
        # stream_id is the event-bus scope (always == session.id). colony_id
        # is the on-disk colony name, which is None for a DM session like this one.
        assert session.colony.stream_id == session.id
        # Shares the session's event bus so SSE picks up worker events
        assert session.colony.event_bus is bus
        # No worker_llm configured → falls back to the queen's session LLM.
        assert session.colony._llm is session_llm  # type: ignore[attr-defined]
    finally:
        await session.colony.stop()


@pytest.mark.asyncio
async def test_unified_colony_workers_land_under_queen_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Workers spawned via the unified runtime live under {queen_dir}/workers/."""
    bus = EventBus()
    session = Session(
        id="session_worker_storage",
        event_bus=bus,
        llm=object(),
        loaded_at=0.0,
    )
    session._queen_tools = []  # type: ignore[attr-defined]
    session._queen_tool_executor = None  # type: ignore[attr-defined]

    queen_dir = tmp_path / "queen_storage"
    queen_dir.mkdir()

    manager = SessionManager()
    monkeypatch.setattr(manager, "build_worker_llm", lambda: None)
    await manager._start_unified_colony_runtime(session, queen_dir)

    try:
        # Spawn a worker (it will start an AgentLoop with the dummy LLM
        # and crash quickly — we don't care, we only care about the
        # worker storage dir being created in the right place).
        ids = await session.colony.spawn(task="placeholder task", count=1)
        worker_dir = queen_dir / "workers" / ids[0]
        assert worker_dir.exists()
        assert (worker_dir / "conversations").exists() or worker_dir.exists()

        # And critically — nothing leaked to the process CWD
        assert not (Path.cwd() / "conversations" / "parts").exists()
    finally:
        await session.colony.stop()


@pytest.mark.asyncio
async def test_stop_session_stops_unified_colony(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """stop_session must call colony.stop() so timers/storage release cleanly."""
    bus = EventBus()
    session = Session(
        id="session_stop_test",
        event_bus=bus,
        llm=object(),
        loaded_at=0.0,
    )
    session._queen_tools = []  # type: ignore[attr-defined]
    session._queen_tool_executor = None  # type: ignore[attr-defined]
    queen_dir = tmp_path / "stop_q"
    queen_dir.mkdir()

    manager = SessionManager()
    monkeypatch.setattr(manager, "build_worker_llm", lambda: None)
    await manager._start_unified_colony_runtime(session, queen_dir)
    manager._sessions[session.id] = session
    colony = session.colony
    assert colony is not None and colony.is_running

    await manager.stop_session(session.id)
    assert session.colony is None
    assert not colony.is_running


@pytest.mark.asyncio
async def test_unified_colony_uses_configured_worker_llm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When worker_llm is configured, parallel workers run on it, not the queen's LLM.

    The queen still runs on session.llm (set up in queen_orchestrator and
    NOT touched by _start_unified_colony_runtime). What we verify here is
    that the ColonyRuntime — the parent of all run_worker spawns
    — gets the dedicated worker LLM.
    """
    bus = EventBus()
    queen_llm = object()  # what the queen runs on
    worker_llm_sentinel = object()  # what parallel workers should run on

    session = Session(
        id="session_worker_llm_test",
        event_bus=bus,
        llm=queen_llm,
        loaded_at=0.0,
    )
    session._queen_tools = []  # type: ignore[attr-defined]
    session._queen_tool_executor = None  # type: ignore[attr-defined]

    queen_dir = tmp_path / "queens" / "default" / "sessions" / session.id
    queen_dir.mkdir(parents=True)

    manager = SessionManager()
    monkeypatch.setattr(manager, "build_worker_llm", lambda: worker_llm_sentinel)
    await manager._start_unified_colony_runtime(session, queen_dir)

    try:
        # ColonyRuntime — which hosts every parallel worker — got the
        # worker LLM, NOT the queen's session LLM.
        assert session.colony._llm is worker_llm_sentinel  # type: ignore[attr-defined]
        assert session.colony._llm is not queen_llm  # type: ignore[attr-defined]
    finally:
        await session.colony.stop()
