"""Tests for ``_read_events_tail`` — the events.jsonl tail reader.

Covers both the small-file forward-scan path and the large-file
reverse-tail path. Verifies tail correctness, total count, and the
``truncated`` flag.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from framework.server.routes_sessions import (
    _EVENTS_HISTORY_REVERSE_TAIL_THRESHOLD_BYTES,
    _read_events_tail,
)


def _write_jsonl(path: Path, count: int, *, line_padding: int = 0) -> None:
    """Write ``count`` JSON objects to ``path``, one per line.

    Each object is ``{"i": <index>}`` plus optional padding to control file
    size for testing the path threshold.
    """
    pad = "x" * line_padding
    with open(path, "w", encoding="utf-8") as f:
        for i in range(count):
            obj = {"i": i, "pad": pad} if pad else {"i": i}
            f.write(json.dumps(obj) + "\n")


def test_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    p.write_text("", encoding="utf-8")
    events, total, truncated = _read_events_tail(p, limit=2000)
    assert events == []
    assert total == 0
    assert truncated is False


def test_small_file_under_limit(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    _write_jsonl(p, count=5)
    events, total, truncated = _read_events_tail(p, limit=2000)
    assert [e["i"] for e in events] == [0, 1, 2, 3, 4]
    assert total == 5
    assert truncated is False


def test_small_file_over_limit_returns_tail(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    _write_jsonl(p, count=100)
    events, total, truncated = _read_events_tail(p, limit=10)
    assert [e["i"] for e in events] == list(range(90, 100))
    assert total == 100
    assert truncated is True


def test_blank_lines_ignored(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        f.write('{"i": 0}\n')
        f.write("\n")
        f.write('{"i": 1}\n')
        f.write("   \n")
        f.write('{"i": 2}\n')
    events, total, _ = _read_events_tail(p, limit=2000)
    assert [e["i"] for e in events] == [0, 1, 2]
    assert total == 3


def test_no_trailing_newline_small(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        f.write('{"i": 0}\n{"i": 1}')
    events, total, _ = _read_events_tail(p, limit=2000)
    assert [e["i"] for e in events] == [0, 1]
    assert total == 2


def test_large_file_uses_reverse_tail(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    # Pad each line so the file exceeds the reverse-tail threshold even with
    # a modest event count. This forces the reverse-tail code path.
    bytes_per_line = 4096
    line_count = (_EVENTS_HISTORY_REVERSE_TAIL_THRESHOLD_BYTES // bytes_per_line) + 50
    _write_jsonl(p, count=line_count, line_padding=bytes_per_line - 64)
    assert p.stat().st_size > _EVENTS_HISTORY_REVERSE_TAIL_THRESHOLD_BYTES

    events, total, truncated = _read_events_tail(p, limit=10)
    assert [e["i"] for e in events] == list(range(line_count - 10, line_count))
    assert total == line_count
    assert truncated is True


def test_large_file_no_trailing_newline(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    bytes_per_line = 4096
    line_count = (_EVENTS_HISTORY_REVERSE_TAIL_THRESHOLD_BYTES // bytes_per_line) + 5
    pad = "x" * (bytes_per_line - 64)
    with open(p, "w", encoding="utf-8") as f:
        for i in range(line_count - 1):
            f.write(json.dumps({"i": i, "pad": pad}) + "\n")
        # Last line, no trailing newline.
        f.write(json.dumps({"i": line_count - 1, "pad": pad}))
    assert p.stat().st_size > _EVENTS_HISTORY_REVERSE_TAIL_THRESHOLD_BYTES

    events, total, _ = _read_events_tail(p, limit=3)
    assert [e["i"] for e in events] == [line_count - 3, line_count - 2, line_count - 1]
    assert total == line_count


def test_large_file_limit_larger_than_file(tmp_path: Path) -> None:
    p = tmp_path / "events.jsonl"
    bytes_per_line = 4096
    line_count = (_EVENTS_HISTORY_REVERSE_TAIL_THRESHOLD_BYTES // bytes_per_line) + 3
    _write_jsonl(p, count=line_count, line_padding=bytes_per_line - 64)
    assert p.stat().st_size > _EVENTS_HISTORY_REVERSE_TAIL_THRESHOLD_BYTES

    events, total, truncated = _read_events_tail(p, limit=line_count + 100)
    assert [e["i"] for e in events] == list(range(line_count))
    assert total == line_count
    assert truncated is False


@pytest.mark.parametrize("limit", [1, 2, 7])
def test_small_path_various_limits(tmp_path: Path, limit: int) -> None:
    p = tmp_path / "events.jsonl"
    _write_jsonl(p, count=20)
    events, total, truncated = _read_events_tail(p, limit=limit)
    assert [e["i"] for e in events] == list(range(20 - limit, 20))
    assert total == 20
    assert truncated is True
