from __future__ import annotations

import asyncio
from contextlib import suppress
from unittest.mock import MagicMock

import pytest

from framework.agents.queen import queen_memory_v2
from framework.host.event_bus import EventBus
from framework.llm.mock import MockLLMProvider
from framework.loader.tool_registry import ToolRegistry
from framework.server.queen_orchestrator import create_queen
from framework.server.session_manager import Session


@pytest.mark.asyncio
async def test_create_queen_injects_identity_into_initial_prompt(monkeypatch, tmp_path) -> None:
    """The first queen prompt should already include the selected profile."""
    monkeypatch.setattr(queen_memory_v2, "MEMORIES_DIR", tmp_path / "memories")

    session = Session(
        id="session_test",
        event_bus=EventBus(),
        llm=MockLLMProvider(),
        loaded_at=0.0,
        queen_name="queen_technology",
    )
    manager = MagicMock()
    manager._subscribe_worker_handoffs = MagicMock()
    queen_profile = {
        "name": "Alexandra",
        "title": "Head of Technology",
        "core_traits": "A pragmatic technical leader.",
    }

    task = await create_queen(
        session=session,
        session_manager=manager,
        worker_identity=None,
        queen_dir=tmp_path / "queen",
        queen_profile=queen_profile,
        initial_prompt="who are you",
        initial_phase="independent",
        tool_registry=ToolRegistry(),
    )

    try:
        assert session.phase_state is not None
        assert "<core_identity>" in session.phase_state.queen_identity_prompt
        assert "Alexandra" in session.phase_state.queen_identity_prompt
        assert "Head of Technology" in session.phase_state.queen_identity_prompt

        prompt = session.phase_state.get_current_prompt()
        assert prompt.startswith(session.phase_state.queen_identity_prompt)
        assert "<core_identity>" in prompt
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
