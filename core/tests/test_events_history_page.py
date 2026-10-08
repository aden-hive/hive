"""Tests for ``_read_events_page`` — the cursor-based backward pager.

Covers both the small and large (cross-1MB-threshold) read paths, files with
and without a trailing newline, and the full client paging loop: stitching
backward pages must reproduce the whole log with no gaps or overlaps, the
byte-offset cursor must march down to 0, and the handler's absolute index /
``seq`` math (replicated here) must stay contiguous with the newest event's
index equal to ``total``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from framework.server import routes_sessions
from framework.server.routes_sessions import (
    _EVENTS_HISTORY_REVERSE_TAIL_THRESHOLD_BYTES,
    _read_events_page,
)


def _write_jsonl(path: Path, count: int, *, line_padding: int = 0, trailing_newline: bool = True) -> None:
    pad = "x" * line_padding
    lines = [json.dumps({"i": i, "pad": pad} if pad else {"i": i}) for i in range(count)]
    text = "\n".join(lines)
    if trailing_newline and count > 0:
        text += "\n"
    path.write_text(text, encoding="utf-8")


def _page_all(path: Path, limit: int) -> tuple[int, list[list[int]], list[int]]:
    """Replay the client loop: tail page first, then backward by cursor.

    Returns ``(total, pages_newest_first, seqs)`` where each page is its
    ``[i, ...]`` values (oldest-first within the page) and ``seqs`` is the flat
    list of absolute seqs in file order, computed exactly as the handler does.
    """
    pages: list[list[int]] = []
    seqs_by_page: list[list[int]] = []

    events, start_offset, total = _read_events_page(path, limit, None)
    returned = len(events)
    start_index = max(1, total - returned + 1) if returned else 1
    pages.append([e["i"] for e in events])
    seqs_by_page.append([start_index + k for k in range(returned)])

    before_offset, before_index = start_offset, start_index
    while before_offset > 0:
        events, start_offset, _ = _read_events_page(path, limit, before_offset)
        returned = len(events)
        si = max(1, before_index - returned)
        pages.append([e["i"] for e in events])
        seqs_by_page.append([si + k for k in range(returned)])
        before_offset, before_index = start_offset, si

    # Flatten oldest-first for whole-log assertions.
    flat_seqs = [s for page in reversed(seqs_by_page) for s in page]
    return total, pages, flat_seqs


@pytest.mark.parametrize("trailing", [True, False])
@pytest.mark.parametrize(
    "count,limit",
    [(0, 5), (1, 5), (5, 5), (10, 5), (12, 5), (50, 10), (3, 500)],
)
def test_small_file_paging(tmp_path: Path, count: int, limit: int, trailing: bool) -> None:
    p = tmp_path / "events.jsonl"
    if count == 0:
        p.write_text("", encoding="utf-8")
    else:
        _write_jsonl(p, count, trailing_newline=trailing)

    total, pages, seqs = _page_all(p, limit)

    # Stitch newest-first pages back into the full oldest-first sequence.
    # Pages come newest-first; prepend each to rebuild the oldest-first log.
    stitched: list[int] = []
    for page in pages:
        stitched = page + stitched
    assert stitched == list(range(count))
    assert total == count
    # seq is the absolute 1-based line index: contiguous 1..count.
    assert seqs == list(range(1, count + 1))
    # The newest event's seq equals total (matches runtime seq for live dedup).
    if count:
        assert seqs[-1] == count
    # No page exceeds the limit.
    assert all(len(page) <= limit for page in pages)


@pytest.mark.parametrize("trailing", [True, False])
def test_large_file_paging_crosses_threshold(tmp_path: Path, trailing: bool) -> None:
    p = tmp_path / "events.jsonl"
    # Pad each line so the file comfortably exceeds the reverse-tail threshold,
    # exercising the chunked backward read across multiple pages.
    _write_jsonl(p, count=300, line_padding=8192, trailing_newline=trailing)
    assert p.stat().st_size > _EVENTS_HISTORY_REVERSE_TAIL_THRESHOLD_BYTES

    total, pages, seqs = _page_all(p, limit=50)

    # Pages come newest-first; prepend each to rebuild the oldest-first log.
    stitched: list[int] = []
    for page in pages:
        stitched = page + stitched
    assert stitched == list(range(300))
    assert total == 300
    assert seqs == list(range(1, 301))
    # 300 events / 50 per page = 6 pages, no overlaps.
    assert len(pages) == 6
    assert sum(len(page) for page in pages) == 300


def test_first_page_is_the_tail(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    _write_jsonl(p, count=100)
    events, start_offset, total = _read_events_page(p, limit=10, before_offset=None)
    assert [e["i"] for e in events] == list(range(90, 100))
    assert total == 100
    assert start_offset > 0  # older events remain → has_more_older


def test_total_not_recomputed_on_cursor_pages(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    _write_jsonl(p, count=20)
    _events, start_offset, total = _read_events_page(p, limit=5, before_offset=None)
    assert total == 20
    # Cursor page: total is -1 (skipped to keep the read O(page)).
    _events2, _so2, total2 = _read_events_page(p, limit=5, before_offset=start_offset)
    assert total2 == -1


def test_final_page_signals_no_more(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    _write_jsonl(p, count=12)
    # Walk to the last page; its start_offset must be 0.
    _events, start_offset, _ = _read_events_page(p, limit=5, before_offset=None)
    last_offset = start_offset
    while start_offset > 0:
        last_offset = start_offset
        _events, start_offset, _ = _read_events_page(p, limit=5, before_offset=last_offset)
    assert start_offset == 0


def test_missing_offset_zero_is_empty(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    _write_jsonl(p, count=10)
    events, start_offset, total = _read_events_page(p, limit=5, before_offset=0)
    assert events == []
    assert start_offset == 0
    # before_offset is not None here, so total stays -1 (cursor-read contract).
    assert total == -1


# ---------------------------------------------------------------------------
# Handler: the worker-thread read is bounded so a saturated pool can't hang
# session loading (long-idle 'no session loads' fix).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_events_history_handler_success(tmp_path: Path, monkeypatch) -> None:
    """Happy path through the HTTP handler still returns the events 200."""
    from aiohttp.test_utils import make_mocked_request

    sid = "session_20260101_ok"
    queen_dir = tmp_path / "queens" / "q" / "sessions" / sid
    queen_dir.mkdir(parents=True)
    _write_jsonl(queen_dir / "events.jsonl", count=3)
    monkeypatch.setattr(
        "framework.server.session_manager._find_queen_session_dir",
        lambda _sid: queen_dir,
    )

    req = make_mocked_request("GET", f"/api/sessions/{sid}/events/history", match_info={"session_id": sid})
    resp = await routes_sessions.handle_session_events_history(req)
    assert resp.status == 200


@pytest.mark.asyncio
async def test_events_history_times_out_instead_of_hanging(tmp_path: Path, monkeypatch) -> None:
    """If the worker-thread read can't complete in time (the symptom of a
    saturated thread pool), the handler returns a fast retryable 503 instead
    of hanging the request — and the desktop's loading overlay — forever."""
    import time

    from aiohttp.test_utils import make_mocked_request

    sid = "session_20260101_timeout"
    queen_dir = tmp_path / "queens" / "q" / "sessions" / sid
    queen_dir.mkdir(parents=True)
    (queen_dir / "events.jsonl").write_text('{"type":"x","seq":1}\n', encoding="utf-8")
    monkeypatch.setattr(
        "framework.server.session_manager._find_queen_session_dir",
        lambda _sid: queen_dir,
    )

    # Block the read longer than the (shrunk) timeout so wait_for fires.
    def _slow_read(*_a, **_k):
        time.sleep(0.5)
        return ([], 0, 0)

    monkeypatch.setattr(routes_sessions, "_read_events_page", _slow_read)
    monkeypatch.setattr(routes_sessions, "_EVENTS_HISTORY_READ_TIMEOUT_S", 0.05)

    req = make_mocked_request("GET", f"/api/sessions/{sid}/events/history", match_info={"session_id": sid})
    resp = await routes_sessions.handle_session_events_history(req)
    assert resp.status == 503
