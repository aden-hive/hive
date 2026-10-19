"""Cold-session listing order.

``list_cold_sessions`` must return queen DM sessions strict newest-*created*
first. Session dirs are named ``session_YYYYMMDD_HHMMSS_<hash>``, so a
descending sort on the directory name is a creation-time sort — total and
deterministic, including the hash tiebreak for same-second creations.
"""

from __future__ import annotations

from pathlib import Path

from framework.server.session_manager import SessionManager


def _make_session_dir(queens_dir: Path, queen_id: str, session_id: str) -> None:
    (queens_dir / queen_id / "sessions" / session_id).mkdir(parents=True, exist_ok=True)


def test_list_cold_sessions_is_strict_newest_created_first(
    _isolate_hive_home_autouse: Path,
) -> None:
    queens_dir = _isolate_hive_home_autouse / "agents" / "queens"

    # Created in an order that matches neither creation-time order nor any
    # obvious filesystem order — a sort bug (e.g. relying on iterdir order or
    # a tieless key) would surface here.
    ids = [
        "session_20260514_120000_aaaaaaaa",
        "session_20260516_090000_cccccccc",  # newest by date
        "session_20260515_080000_bbbbbbbb",
        "session_20260514_120000_dddddddd",  # same timestamp as the first
    ]
    for sid in ids:
        _make_session_dir(queens_dir, "queen_test", sid)

    result = SessionManager.list_cold_sessions()
    got = [r["session_id"] for r in result]

    # Strict descending session_id == newest-created first, with the hash
    # ("dddddddd" > "aaaaaaaa") as a deterministic same-second tiebreak.
    assert got == sorted(ids, reverse=True)


def test_list_cold_sessions_spans_multiple_queens_in_order(
    _isolate_hive_home_autouse: Path,
) -> None:
    queens_dir = _isolate_hive_home_autouse / "agents" / "queens"
    _make_session_dir(queens_dir, "queen_a", "session_20260510_100000_11111111")
    _make_session_dir(queens_dir, "queen_b", "session_20260517_100000_22222222")
    _make_session_dir(queens_dir, "queen_a", "session_20260512_100000_33333333")

    got = [r["session_id"] for r in SessionManager.list_cold_sessions()]
    assert got == [
        "session_20260517_100000_22222222",
        "session_20260512_100000_33333333",
        "session_20260510_100000_11111111",
    ]
