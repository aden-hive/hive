"""One traversal, two policies: session-dir resolution for a shared session id.

A ``session_id`` is not unique on disk — a DM session forked into a colony keeps
its id, and a context-less resume used to materialize a duplicate empty dir under
the queen DM tree. Two separate fixes landed for that one fact from opposite
ends: ``_iter_queen_session_dirs`` (yield every match, so the attachment handler
can serve the dir that actually holds the file) and ``_derive_resume_colony_id``
(recover the owning colony, so the duplicate is never created).

Both now read through the same generator. These pin the part that would silently
regress if they drift apart again: the generator yields the DM-tree candidate
FIRST, so any consumer wanting the colony must look past it.
"""

from __future__ import annotations

from pathlib import Path

import framework.config as hive_config
from framework.server import session_manager as sm

QUEEN = "queen_growth"
COLONY = "icp_outreach"
SID = "session_20260728_202550_96d649af"


def _patch_storage(monkeypatch, tmp_path: Path) -> Path:
    hive = tmp_path / ".hive"
    monkeypatch.setattr(sm, "QUEENS_DIR", hive / "queens")
    monkeypatch.setattr(hive_config, "QUEENS_DIR", hive / "queens")
    monkeypatch.setattr(sm, "COLONIES_DIR", hive / "colonies")
    monkeypatch.setattr(hive_config, "COLONIES_DIR", hive / "colonies")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    return hive


def _dm_dir(hive: Path) -> Path:
    return hive / "queens" / QUEEN / "sessions" / SID


def _colony_dir(hive: Path) -> Path:
    return hive / "colonies" / COLONY / "queens" / QUEEN / "sessions" / SID


def test_colony_id_read_off_the_session_path():
    assert sm._colony_id_for_session_dir(Path("/h/colonies/acme/queens/queen_growth/sessions/s1")) == "acme"


def test_queen_dm_session_path_has_no_colony():
    """A DM session is not owned by a colony — the distinction the resume guard
    turns on, so it must not be inferred from an unrelated path component."""
    assert sm._colony_id_for_session_dir(Path("/h/queens/queen_growth/sessions/s1")) is None


def test_generator_finds_a_colony_only_session(monkeypatch, tmp_path):
    hive = _patch_storage(monkeypatch, tmp_path)
    _colony_dir(hive).mkdir(parents=True)
    assert list(sm._iter_queen_session_dirs(SID)) == [_colony_dir(hive)]


def test_generator_yields_every_dir_sharing_an_id(monkeypatch, tmp_path):
    """The attachment handler depends on this: the chip URL carries only id +
    basename, so serving the first match 404s when the file lives in the other
    copy of the same session."""
    hive = _patch_storage(monkeypatch, tmp_path)
    _dm_dir(hive).mkdir(parents=True)
    _colony_dir(hive).mkdir(parents=True)
    found = list(sm._iter_queen_session_dirs(SID))
    assert set(found) == {_dm_dir(hive), _colony_dir(hive)}
    # DM tree is scanned first — the ordering every consumer below has to survive.
    assert found[0] == _dm_dir(hive)


def test_resume_colony_is_found_despite_a_duplicate_dm_dir(monkeypatch, tmp_path):
    """The regression that matters. The duplicate empty DM dir is exactly the
    artifact this guard exists to prevent, and it sorts FIRST out of the shared
    generator — so a consumer that just took the first candidate would return
    None here and re-create the "blank history" bug it was written to stop."""
    hive = _patch_storage(monkeypatch, tmp_path)
    _dm_dir(hive).mkdir(parents=True)
    _colony_dir(hive).mkdir(parents=True)
    assert sm._derive_resume_colony_id(SID) == COLONY


def test_resume_colony_is_none_for_a_real_dm_session(monkeypatch, tmp_path):
    """A genuine DM session must stay unbound — binding it to a colony would
    route the user's own DM history into a colony page."""
    hive = _patch_storage(monkeypatch, tmp_path)
    _dm_dir(hive).mkdir(parents=True)
    assert sm._derive_resume_colony_id(SID) is None


def test_resume_colony_is_none_when_nothing_matches(monkeypatch, tmp_path):
    _patch_storage(monkeypatch, tmp_path)
    assert sm._derive_resume_colony_id(SID) is None


def test_first_match_lookup_still_prefers_the_dm_tree(monkeypatch, tmp_path):
    """``_find_queen_session_dir`` keeps its first-match contract — many read
    paths depend on it, and the fix for the duplicate-dir bug is to stop
    creating the duplicate, not to change what this returns."""
    hive = _patch_storage(monkeypatch, tmp_path)
    _dm_dir(hive).mkdir(parents=True)
    _colony_dir(hive).mkdir(parents=True)
    assert sm._find_queen_session_dir(SID) == _dm_dir(hive)
