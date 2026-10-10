"""Tests for ``memory_tools.recall`` (auto-injected excerpts) and ``memory_tools.timeline``."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from memory_tools import recall as R, timeline as T

QUEEN = "queen_test"


@pytest.fixture
def hive_home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("HIVE_HOME", str(tmp_path))
    return tmp_path


def _session(hive_home: Path, session: str, turns: list[tuple[str, str]], timeline: list[dict] | None = None) -> Path:
    """A finished queen session: alternating user/assistant turns, optional timeline."""
    sdir = hive_home / "queens" / QUEEN / "sessions" / session
    sdir.mkdir(parents=True)
    events = []
    for i, (role, text) in enumerate(turns):
        if role == "user":
            events.append({"type": "client_input_received", "data": {"content": text}})
        else:
            events.append({"type": "client_output_delta", "data": {"snapshot": text, "iteration": i, "inner_turn": 0}})
    (sdir / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    if timeline is not None:
        (sdir / "timeline.jsonl").write_text("".join(json.dumps(i) + "\n" for i in timeline), encoding="utf-8")
    return sdir


# ---------------------------------------------------------------------------
# recall
# ---------------------------------------------------------------------------


def test_query_terms_drop_scaffolding_and_stem() -> None:
    assert R.query_terms("How many weddings have I attended in the past few months?") == ["wedding", "attend"]
    assert R.query_terms("thanks!") == []


def test_recall_finds_the_turn_that_answers(hive_home: Path) -> None:
    _session(
        hive_home,
        "session_20230522_211800_aaaa0001",
        [
            ("user", "I've been listening to audiobooks during my daily commute, which takes 45 minutes each way."),
            ("assistant", "That's a great use of the time. Here are some fiction picks..."),
        ],
    )
    _session(
        hive_home,
        "session_20230524_143200_aaaa0002",
        [("user", "What can individuals do to help coral reef conservation?"), ("assistant", "Reduce runoff...")],
    )

    turns = R.recall("queens", QUEEN, "How long is my daily commute to work?")

    assert [t.session for t in turns] == ["session_20230522_211800_aaaa0001"]
    block = R.render(turns, "How long is my daily commute to work?")
    assert "2023-05-22 (Mon)" in block
    assert "45 minutes each way" in block


def test_recall_excludes_the_live_session_and_stays_quiet_when_nothing_relates(hive_home: Path) -> None:
    live = "session_20230601_090000_aaaa0003"
    _session(hive_home, live, [("user", "My commute is brutal today."), ("assistant", "Sorry to hear that.")])

    assert R.recall("queens", QUEEN, "Remind me how long my commute is", exclude_session=live) == []
    assert R.recall_block("queens", QUEEN, "Write a haiku about autumn leaves") is None


def test_one_shared_common_word_is_not_enough(hive_home: Path) -> None:
    common = [("user", "Planning day {i}: errands, groceries, laundry."), ("assistant", "Sounds good.")]
    for i in range(60):
        _session(hive_home, f"session_202305{(i % 28) + 1:02d}_1000{i:02d}_bbbb{i:04d}", [(r, t.format(i=i)) for r, t in common])

    # "planning" matches every session, "telescope" matches none.
    assert R.recall("queens", QUEEN, "Planning to buy a telescope?") == []


# ---------------------------------------------------------------------------
# timeline search
# ---------------------------------------------------------------------------


def _item(text: str, start: str, end: str | None = None, kind: str = "event", aliases: tuple[str, ...] = (), turn: int = 1) -> dict:
    return {"turn": turn, "kind": kind, "text": text, "start": start, "end": end or start, "aliases": list(aliases)}


@pytest.fixture
def weddings(hive_home: Path) -> None:
    _session(
        hive_home,
        "session_20230901_100000_cccc0001",
        [("user", "...")],
        [
            _item("The user attended cousin Rachel's vineyard wedding.", "2023-08-01", "2023-08-31", aliases=("went to a wedding",)),
            _item("The user is planning their own beach wedding.", "2023-09-01", kind="plan"),
        ],
    )
    _session(
        hive_home,
        "session_20231015_100000_cccc0002",
        [("user", "...")],
        [
            _item("The user attended Jen and Tom's barn wedding.", "2023-10-07", "2023-10-08"),
            _item("The user was a bridesmaid in 2021.", "2021-06-12", aliases=("wedding party",)),
        ],
    )


def test_search_filters_by_date_overlap_and_sorts_oldest_first(weddings) -> None:
    res = T.search("queens", QUEEN, "wedding", since=date(2023, 1, 1), kind="event")

    assert [i["text"] for i in res["items"]] == [
        "The user attended cousin Rachel's vineyard wedding.",
        "The user attended Jen and Tom's barn wedding.",
    ]
    assert res["items"][0]["when"] == "2023-08-01..2023-08-31"
    assert res["items"][0]["said_on"] == "2023-09-01"
    assert res["sessions_with_timeline"] == 2


def test_search_matches_aliases_and_kinds(weddings) -> None:
    hits = T.search("queens", QUEEN, "wedding party")
    assert [i["text"] for i in hits["items"]] == ["The user was a bridesmaid in 2021."]

    plans = T.search("queens", QUEEN, ".", kind="plan")
    assert [i["kind"] for i in plans["items"]] == ["plan"]

    # A range ending inside an item still overlaps it.
    august = T.search("queens", QUEEN, "rachel", since=date(2023, 8, 20), until=date(2023, 8, 21))
    assert len(august["items"]) == 1


def test_search_truncates_and_reports_total(weddings) -> None:
    res = T.search("queens", QUEEN, ".", max_results=2)
    assert len(res["items"]) == 2 and res["total"] == 4 and res["truncated"]


def test_search_is_empty_without_timelines(hive_home: Path) -> None:
    _session(hive_home, "session_20230901_100000_dddd0001", [("user", "hello")])
    assert T.search("queens", QUEEN, ".") == {"items": [], "total": 0, "truncated": False, "sessions_with_timeline": 0}


def test_colony_scope_covers_every_overseeing_queens_sessions(hive_home: Path) -> None:
    """A colony's history lives under each queen that oversaw it."""
    for queen, session, text in (
        ("queen_a", "session_20230301_100000_eeee0001", "We shipped the billing migration to Postgres."),
        ("queen_b", "session_20230302_100000_eeee0002", "The billing migration rollback plan is ready."),
    ):
        sdir = hive_home / "colonies" / "acme" / "queens" / queen / "sessions" / session
        sdir.mkdir(parents=True)
        events = [{"type": "client_input_received", "data": {"content": text}}]
        (sdir / "events.jsonl").write_text(json.dumps(events[0]) + "\n", encoding="utf-8")
        (sdir / "timeline.jsonl").write_text(json.dumps(_item(text, "2023-03-01")) + "\n", encoding="utf-8")

    turns = R.recall("colonies", "acme", "What happened with the billing migration?")
    assert {t.session for t in turns} == {"session_20230301_100000_eeee0001", "session_20230302_100000_eeee0002"}
    assert T.search("colonies", "acme", "billing")["total"] == 2
