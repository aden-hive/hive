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
) -> None:
    """The helper builds a ColonyRuntime, starts it, and stashes it on session.colony."""
    bus = EventBus()
    session = Session(
        id="session_phase2_test",
        event_bus=bus,
        llm=object(),  # not invoked in this test
        loaded_at=0.0,
    )
    # _start_unified_colony_runtime reads these — usually create_queen
    # stashes them, but here we set them directly.
    session._queen_tools = []  # type: ignore[attr-defined]
    session._queen_tool_executor = None  # type: ignore[attr-defined]

    queen_dir = tmp_path / "queens" / "default" / "sessions" / session.id
    queen_dir.mkdir(parents=True)

    manager = SessionManager()
    await manager._start_unified_colony_runtime(session, queen_dir)

    try:
        assert session.colony is not None
        assert isinstance(session.colony, ColonyRuntime)
        assert session.colony.is_running
        assert session.colony.colony_id == session.id
        # Shares the session's event bus so SSE picks up worker events
        assert session.colony.event_bus is bus
    finally:
        await session.colony.stop()


@pytest.mark.asyncio
async def test_unified_colony_workers_land_under_queen_dir(
    tmp_path: Path,
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
async def test_stop_session_stops_unified_colony(tmp_path: Path) -> None:
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
    await manager._start_unified_colony_runtime(session, queen_dir)
    manager._sessions[session.id] = session
    colony = session.colony
    assert colony is not None and colony.is_running

    await manager.stop_session(session.id)
    assert session.colony is None
    assert not colony.is_running
