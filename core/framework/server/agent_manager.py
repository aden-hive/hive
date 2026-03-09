"""Backward-compatibility shim.

The primary implementation is now in ``session_manager.py``.
This module re-exports ``SessionManager`` as ``AgentManager`` and
keeps ``AgentSlot`` for test compatibility.
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from framework.server.session_manager import Session, SessionManager  # noqa: F401


@dataclass
class AgentSlot:
    """Legacy data class — kept for test compatibility only.

    New code should use ``Session`` from ``session_manager``.
    """

    id: str
    agent_path: Path
    runner: Any
    runtime: Any
    info: Any
    loaded_at: float
    queen_executor: Any = None
    queen_task: asyncio.Task | None = None
    judge_task: asyncio.Task | None = None
    escalation_sub: str | None = None


# Backward compat alias
AgentManager = SessionManager
