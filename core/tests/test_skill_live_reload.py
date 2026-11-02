"""Which running catalogs a skill change reloads (framework.skills.live_reload)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from framework.skills.live_reload import reload_live_skills, reload_runtimes
from framework.skills.manager import SkillsManager


class _CountingSkillsManager(SkillsManager):
    def __init__(self) -> None:
        super().__init__()
        self.reloads = 0

    def reload(self) -> None:
        self.reloads += 1


class _Colony:
    def __init__(self, queen_id: str) -> None:
        self.queen_id = queen_id
        self.reloads = 0

    async def reload_skills(self) -> None:
        self.reloads += 1


class _SessionManager:
    """The lookups SessionManager offers, over a fixed set of live sessions."""

    def __init__(self, sessions: list[SimpleNamespace]) -> None:
        self._sessions = sessions

    def list_sessions(self) -> list[SimpleNamespace]:
        return list(self._sessions)

    def iter_queen_sessions(self, queen_id: str):
        return (s for s in self._sessions if s.queen_name == queen_id)

    def iter_colony_runtimes(self, *, queen_id=None, colony_id=None):
        return (s.colony for s in self._sessions if s.colony is not None and queen_id in (None, s.colony.queen_id))


def _session(queen_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        queen_name=queen_id,
        phase_state=SimpleNamespace(skills_manager=_CountingSkillsManager()),
        colony=_Colony(queen_id),
    )


@pytest.mark.asyncio
async def test_a_queens_skill_reloads_only_her_sessions_and_colonies() -> None:
    ava, ivy = _session("queen_ava"), _session("queen_ivy")

    await reload_live_skills(_SessionManager([ava, ivy]), queen_id="queen_ava")

    assert (ava.phase_state.skills_manager.reloads, ava.colony.reloads) == (1, 1)
    assert (ivy.phase_state.skills_manager.reloads, ivy.colony.reloads) == (0, 0)


@pytest.mark.asyncio
async def test_a_shared_skill_reloads_everyone() -> None:
    ava, ivy = _session("queen_ava"), _session("queen_ivy")

    await reload_live_skills(_SessionManager([ava, ivy]))

    assert [s.phase_state.skills_manager.reloads for s in (ava, ivy)] == [1, 1]
    assert [s.colony.reloads for s in (ava, ivy)] == [1, 1]


@pytest.mark.asyncio
async def test_one_failing_reload_does_not_stop_the_others() -> None:
    class _Broken:
        async def reload_skills(self) -> None:
            raise RuntimeError("disk gone")

    colony = _Colony("queen_ava")

    await reload_runtimes([_Broken(), colony])

    assert colony.reloads == 1
