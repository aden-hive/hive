"""Tests for the session summary sidecar cache."""

from __future__ import annotations

import json
import time
from pathlib import Path

from framework.storage import session_summary


def _make_session_dir(tmp_path: Path) -> Path:
    d = tmp_path / "session_x"
    (d / "conversations" / "parts").mkdir(parents=True)
    return d


def _write_part(session_dir: Path, seq: int, data: dict) -> None:
    parts_dir = session_dir / "conversations" / "parts"
    p = parts_dir / f"{seq:010d}.json"
    p.write_text(json.dumps(data), encoding="utf-8")


def test_is_client_facing() -> None:
    assert session_summary.is_client_facing({"role": "user", "content": "hi"})
    assert session_summary.is_client_facing({"role": "assistant", "content": "ok"})
    assert not session_summary.is_client_facing({"role": "tool", "content": "x"})
    assert not session_summary.is_client_facing({"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]})
    assert not session_summary.is_client_facing({"is_transition_marker": True})


def test_rebuild_empty_session(tmp_path: Path) -> None:
    d = _make_session_dir(tmp_path)
    summary = session_summary.rebuild_summary(d)
    assert summary is not None
    assert summary["message_count"] == 0
    assert summary["last_message"] is None
    assert summary["last_active_at"] == 0.0
    # Persisted to disk
    assert (d / "summary.json").exists()


def test_rebuild_counts_only_client_facing(tmp_path: Path) -> None:
    d = _make_session_dir(tmp_path)
    _write_part(d, 0, {"role": "user", "content": "hello", "seq": 0, "created_at": 1.0})
    _write_part(d, 1, {"role": "assistant", "content": "", "tool_calls": [{"id": "1"}], "seq": 1, "created_at": 2.0})
    _write_part(d, 2, {"role": "tool", "content": "result", "seq": 2, "created_at": 3.0})
    _write_part(d, 3, {"role": "assistant", "content": "answer", "seq": 3, "created_at": 4.0})

    summary = session_summary.rebuild_summary(d)
    assert summary["message_count"] == 2  # user + final assistant
    assert summary["last_message"] == "answer"
    assert summary["last_active_at"] == 4.0
    assert summary["last_part_seq"] == 3


def test_rebuild_truncates_long_message(tmp_path: Path) -> None:
    d = _make_session_dir(tmp_path)
    long = "a" * 500
    _write_part(d, 0, {"role": "assistant", "content": long, "seq": 0, "created_at": 1.0})
    summary = session_summary.rebuild_summary(d)
    assert summary["last_message"] is not None
    assert len(summary["last_message"]) == 120


def test_rebuild_handles_anthropic_content_blocks(tmp_path: Path) -> None:
    d = _make_session_dir(tmp_path)
    _write_part(
        d,
        0,
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "block one"},
                {"type": "text", "text": "block two"},
            ],
            "seq": 0,
            "created_at": 1.0,
        },
    )
    summary = session_summary.rebuild_summary(d)
    assert summary["last_message"] == "block one block two"


def test_update_summary_increments(tmp_path: Path) -> None:
    d = _make_session_dir(tmp_path)
    session_summary.update_summary(d, {"role": "user", "content": "hi", "seq": 0, "created_at": 1.0})
    s = session_summary.read_summary(d)
    assert s["message_count"] == 1
    assert s["last_active_at"] == 1.0

    session_summary.update_summary(d, {"role": "assistant", "content": "ok", "seq": 1, "created_at": 2.0})
    s = session_summary.read_summary(d)
    assert s["message_count"] == 2
    assert s["last_message"] == "ok"
    assert s["last_active_at"] == 2.0


def test_update_summary_skips_non_client_parts(tmp_path: Path) -> None:
    d = _make_session_dir(tmp_path)
    session_summary.update_summary(d, {"role": "tool", "content": "x", "seq": 0, "created_at": 1.0})
    session_summary.update_summary(
        d, {"role": "assistant", "content": "", "tool_calls": [{"id": "x"}], "seq": 1, "created_at": 2.0}
    )
    # Neither part bumps the count or creates a summary file
    assert session_summary.read_summary(d) is None


def test_update_summary_user_message_keeps_prior_assistant_snippet(tmp_path: Path) -> None:
    d = _make_session_dir(tmp_path)
    session_summary.update_summary(d, {"role": "assistant", "content": "answer", "seq": 0, "created_at": 1.0})
    session_summary.update_summary(d, {"role": "user", "content": "next q", "seq": 1, "created_at": 2.0})
    s = session_summary.read_summary(d)
    assert s["message_count"] == 2
    # Last assistant snippet preserved through a user message
    assert s["last_message"] == "answer"
    assert s["last_active_at"] == 2.0


def test_is_stale_when_missing(tmp_path: Path) -> None:
    d = _make_session_dir(tmp_path)
    assert session_summary.is_stale(d) is True


def test_is_stale_after_part_write(tmp_path: Path) -> None:
    d = _make_session_dir(tmp_path)
    # Create a summary, then add a part with a newer mtime.
    session_summary.update_summary(d, {"role": "assistant", "content": "x", "seq": 0, "created_at": 1.0})
    assert session_summary.is_stale(d) is False

    time.sleep(0.05)
    _write_part(d, 1, {"role": "assistant", "content": "y", "seq": 1})
    assert session_summary.is_stale(d) is True


def test_rebuild_picks_up_node_based_layout(tmp_path: Path) -> None:
    d = tmp_path / "sess"
    (d / "conversations" / "node_a" / "parts").mkdir(parents=True)
    (d / "conversations" / "node_b" / "parts").mkdir(parents=True)
    p1 = d / "conversations" / "node_a" / "parts" / "0000000000.json"
    p1.write_text(json.dumps({"role": "user", "content": "hi", "seq": 0, "created_at": 1.0}))
    p2 = d / "conversations" / "node_b" / "parts" / "0000000001.json"
    p2.write_text(json.dumps({"role": "assistant", "content": "yo", "seq": 1, "created_at": 2.0}))

    summary = session_summary.rebuild_summary(d)
    assert summary["message_count"] == 2
    assert summary["last_message"] == "yo"
