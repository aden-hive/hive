"""Tests for ``memory_tools.turn_index``: the index recall reads instead of scanning the mirror."""

from __future__ import annotations

import contextlib
import json
import shutil
from pathlib import Path

import pytest

from memory_tools import paths as P, recall as R, turn_index as TI

QUEEN = "queen_test"


@pytest.fixture
def hive_home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("HIVE_HOME", str(tmp_path))
    return tmp_path


def _events(turns: list[tuple[str, str]], start: int = 0) -> str:
    events = []
    for i, (role, text) in enumerate(turns, start):
        if role == "user":
            events.append({"type": "client_input_received", "data": {"content": text}})
        else:
            events.append({"type": "client_output_delta", "data": {"snapshot": text, "iteration": i, "inner_turn": 0}})
    return "".join(json.dumps(e) + "\n" for e in events)


def _write(hive_home: Path, session: str, turns: list[tuple[str, str]]) -> Path:
    log = hive_home / "queens" / QUEEN / "sessions" / session / "events.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(_events(turns), encoding="utf-8")
    return log


def _append(log: Path, turns: list[tuple[str, str]], start: int) -> None:
    with log.open("a", encoding="utf-8") as f:
        f.write(_events(turns, start))


def _sessions_found(text: str, **kwargs) -> set[str]:
    return {t.session for t in R.recall("queens", QUEEN, text, **kwargs)}


def test_term_counts_cover_every_term_a_query_can_ask_for() -> None:
    assert TI.term_counts("RTX4090 ran hot, so 5 fans") == {"rtx4090": 1, "ran": 1, "hot": 1, "fans": 1, "5": 1}
    assert TI.term_counts("好累啊") == {"好累": 1, "累啊": 1}
    # A word beside Chinese text is still a word.
    assert TI.term_counts("用python写") == {"python": 1}


def test_a_word_beside_chinese_text_is_found(hive_home: Path) -> None:
    _write(hive_home, "session_20260101_000000_aaa", [("user", "我一直用python写脚本"), ("assistant", "好的")])

    assert _sessions_found("python scripts") == {"session_20260101_000000_aaa"}


def test_recall_picks_up_a_new_session_and_new_turns(hive_home: Path) -> None:
    first = "session_20260101_000000_aaa"
    log = _write(hive_home, first, [("user", "My commute takes 45 minutes"), ("assistant", "Noted")])
    assert _sessions_found("commute") == {first}

    _append(log, [("user", "The ferry schedule changed"), ("assistant", "Sorry to hear")], 2)
    assert _sessions_found("ferry schedule") == {first}

    second = "session_20260102_000000_bbb"
    _write(hive_home, second, [("user", "The ferry broke down"), ("assistant", "Oh no")])
    assert _sessions_found("ferry schedule") == {first, second}


def test_a_reply_still_being_written_is_reindexed_and_loses_the_terms_it_dropped(hive_home: Path) -> None:
    log = _write(hive_home, "session_20260101_000000_aaa", [("user", "Plan the garden"), ("assistant", "Tomatoes first")])
    assert _sessions_found("tomatoes")

    # The same model turn streamed further: its snapshot replaces what was there.
    _append(log, [("assistant", "Cucumbers first")], 1)

    assert _sessions_found("cucumbers")
    assert not _sessions_found("tomatoes")


def test_a_rewritten_log_starts_the_session_over(hive_home: Path) -> None:
    session = "session_20260101_000000_aaa"
    log = _write(hive_home, session, [("user", "A long talk about tomatoes and many other things"), ("assistant", "Yes")])
    assert _sessions_found("tomatoes") == {session}

    log.write_text(_events([("user", "Cucumbers")]), encoding="utf-8")

    assert _sessions_found("tomatoes") == set()
    assert _sessions_found("cucumbers") == {session}


def test_a_session_gone_from_disk_and_mirror_is_forgotten(hive_home: Path) -> None:
    session = "session_20260101_000000_aaa"
    log = _write(hive_home, session, [("user", "Tomatoes all summer"), ("assistant", "Lovely")])
    assert _sessions_found("tomatoes") == {session}

    shutil.rmtree(log.parent)
    # The mirror outlives its source, as it did for the scan this replaces.
    assert _sessions_found("tomatoes") == {session}

    shutil.rmtree(P.events_index_dir("queens", QUEEN, session))
    assert _sessions_found("tomatoes") == set()


def test_the_live_session_is_not_indexed_for_its_own_turn(hive_home: Path) -> None:
    live = "session_20260101_000000_live"
    _write(hive_home, live, [("user", "Tomatoes"), ("assistant", "Yes")])

    assert _sessions_found("tomatoes", exclude_session=live) == set()
    with contextlib.closing(TI.connect("queens", QUEEN)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 0

    # Once it isn't the live one, it is caught up.
    assert _sessions_found("tomatoes") == {live}


def test_a_query_answers_while_another_thread_refreshes(hive_home: Path) -> None:
    session = "session_20260101_000000_aaa"
    log = _write(hive_home, session, [("user", "Tomatoes"), ("assistant", "Yes")])
    assert _sessions_found("tomatoes") == {session}

    _append(log, [("user", "Cucumbers"), ("assistant", "Yes")], 2)
    busy = TI._refreshing[P.turn_index_path("queens", QUEEN)]
    with busy:
        # It reads what is there rather than waiting.
        assert _sessions_found("tomatoes") == {session}
        assert _sessions_found("cucumbers") == set()
    assert _sessions_found("cucumbers") == {session}


def test_an_older_index_file_is_rebuilt(hive_home: Path) -> None:
    session = "session_20260101_000000_aaa"
    _write(hive_home, session, [("user", "Tomatoes"), ("assistant", "Yes")])
    assert _sessions_found("tomatoes") == {session}

    with contextlib.closing(TI.connect("queens", QUEEN)) as conn:
        conn.execute(f"PRAGMA user_version = {TI._VERSION - 1}")

    assert _sessions_found("tomatoes") == {session}
    with contextlib.closing(TI.connect("queens", QUEEN)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == TI._VERSION
        assert conn.execute("SELECT COUNT(*) FROM turns").fetchone()[0] == 1


def test_a_session_it_cannot_read_is_tried_again_next_time(hive_home: Path, monkeypatch) -> None:
    session = "session_20260101_000000_aaa"
    _write(hive_home, session, [("user", "Tomatoes"), ("assistant", "Yes")])
    real_sync = TI.sync_session

    def locked(*args, **kwargs):
        raise PermissionError("in use")

    monkeypatch.setattr(TI, "sync_session", locked)
    assert _sessions_found("tomatoes") == set()

    monkeypatch.setattr(TI, "sync_session", real_sync)
    assert _sessions_found("tomatoes") == {session}
