"""Colony-binding derivation for resumes that arrive without colony context.

A ``queen_resume_from`` pointing at a colony overseer session but carrying
no ``colony_id`` (e.g. the desktop's session-gone auto-resume on the queen
DM page) must resolve to the session's on-disk colony. Binding such a
resume to no colony makes ``_start_queen`` materialize a duplicate empty
session dir under the queen DM tree, which ``_find_queen_session_dir``
then prefers over the real colony copy — the user sees a blank history
for a session whose full transcript is intact on disk.
"""

from __future__ import annotations

from pathlib import Path

from framework.server.session_manager import _derive_resume_colony_id

SID = "session_20260719_121546_afe89313"


def _make_colony_session(hive: Path, colony: str, queen: str, sid: str) -> Path:
    d = hive / "colonies" / colony / "queens" / queen / "sessions" / sid
    d.mkdir(parents=True)
    return d


def _make_dm_session(hive: Path, queen: str, sid: str) -> Path:
    d = hive / "agents" / "queens" / queen / "sessions" / sid
    d.mkdir(parents=True)
    return d


def test_colony_session_resolves_to_its_colony(
    _isolate_hive_home_autouse: Path,
) -> None:
    _make_colony_session(_isolate_hive_home_autouse, "email_reply", "queen_outbound", SID)
    assert _derive_resume_colony_id(SID) == "email_reply"


def test_dm_session_yields_none(_isolate_hive_home_autouse: Path) -> None:
    _make_dm_session(_isolate_hive_home_autouse, "queen_outbound", SID)
    assert _derive_resume_colony_id(SID) is None


def test_unknown_session_yields_none(_isolate_hive_home_autouse: Path) -> None:
    assert _derive_resume_colony_id(SID) is None


def test_colony_wins_even_when_a_dm_shadow_exists(
    _isolate_hive_home_autouse: Path,
) -> None:
    # The observed corruption: an earlier context-free resume left an empty
    # duplicate under the DM tree. Derivation must still bind the resume to
    # the colony copy — otherwise the shadow keeps re-electing itself.
    _make_dm_session(_isolate_hive_home_autouse, "queen_outbound", SID)
    _make_colony_session(_isolate_hive_home_autouse, "email_reply", "queen_outbound", SID)
    assert _derive_resume_colony_id(SID) == "email_reply"
