"""Reload the skill catalogs of running queens and colonies after a skill changes on disk.

Nothing watches the skill folders, so whatever changes one (the Skills page, a queen's
``write_skill``, an approved install into the shared library) reloads the live catalogs
itself. A queen reads hers each turn, so she sees the change on her next one.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from typing import Any

from framework.skills.manager import SkillsManager

logger = logging.getLogger(__name__)


class ManagerReloadAdapter:
    """Gives a queen session's bare ``SkillsManager`` the ``reload_skills()`` a colony runtime has.

    A queen session keeps its manager on ``phase_state.skills_manager`` with no runtime around it.
    """

    def __init__(self, skills_manager: SkillsManager) -> None:
        self._mgr = skills_manager

    @property
    def skills_manager(self) -> SkillsManager:
        return self._mgr

    async def reload_skills(self) -> dict[str, Any]:
        async with self._mgr.mutation_lock:
            self._mgr.reload()
        return {"catalog_chars": len(self._mgr.skills_catalog_prompt)}


def live_skill_runtimes(session_manager: Any, *, queen_id: str | None = None) -> list[Any]:
    """The running colonies and queen sessions a skill change reaches, each with ``reload_skills()``.

    With ``queen_id``, that queen's sessions and colonies; without, everyone's (a skill in the
    shared library).
    """
    runtimes: list[Any] = []
    if session_manager is None:
        return runtimes
    try:
        runtimes.extend(session_manager.iter_colony_runtimes(queen_id=queen_id))
        sessions = session_manager.iter_queen_sessions(queen_id) if queen_id else session_manager.list_sessions()
        for session in sessions:
            skills_mgr = getattr(getattr(session, "phase_state", None), "skills_manager", None)
            if isinstance(skills_mgr, SkillsManager):
                runtimes.append(ManagerReloadAdapter(skills_mgr))
    except Exception:
        logger.debug("skills: live manager lookup failed", exc_info=True)
    return runtimes


async def reload_runtimes(runtimes: Iterable[Any]) -> None:
    """Reload each runtime's skills at once; one that fails is logged and the rest still reload."""

    async def reload_one(runtime: Any) -> None:
        try:
            await runtime.reload_skills()
        except Exception:
            logger.warning("reload_skills failed for runtime %r", runtime, exc_info=True)

    await asyncio.gather(*(reload_one(runtime) for runtime in runtimes))


async def reload_live_skills(session_manager: Any, *, queen_id: str | None = None) -> None:
    """Reload the catalogs :func:`live_skill_runtimes` finds."""
    await reload_runtimes(live_skill_runtimes(session_manager, queen_id=queen_id))
