"""Tests for ``compaction_status.sweep_stale_in_progress``.

The sweep runs at server boot and rewrites orphaned ``in_progress`` markers
to ``failed``. Without it, any colony whose compaction was interrupted by a
server crash would block its first cold-load for the full ``await_completion``
timeout before falling through.
"""

from __future__ import annotations

import json
from pathlib import Path

from framework.server import compaction_status


def _seed(queens_root: Path, queen: str, session: str, status: str) -> Path:
    sd = queens_root / queen / "sessions" / session
    sd.mkdir(parents=True)
    (sd / "compaction_status.json").write_text(
        json.dumps({"status": status}),
        encoding="utf-8",
    )
    return sd


def test_sweep_missing_root_is_noop(tmp_path: Path) -> None:
    cleaned = compaction_status.sweep_stale_in_progress(tmp_path / "nope")
    assert cleaned == 0


def test_sweep_clears_in_progress_markers(tmp_path: Path) -> None:
    sd = _seed(tmp_path, "alpha", "session_1", "in_progress")
    cleaned = compaction_status.sweep_stale_in_progress(tmp_path)
    assert cleaned == 1
    final = compaction_status.get_status(sd)
    assert final is not None
    assert final["status"] == "failed"
    assert "server restarted" in final.get("error", "")


def test_sweep_leaves_done_and_failed_alone(tmp_path: Path) -> None:
    done_dir = _seed(tmp_path, "alpha", "s_done", "done")
    failed_dir = _seed(tmp_path, "alpha", "s_failed", "failed")
    cleaned = compaction_status.sweep_stale_in_progress(tmp_path)
    assert cleaned == 0
    assert compaction_status.get_status(done_dir)["status"] == "done"
    assert compaction_status.get_status(failed_dir)["status"] == "failed"


def test_sweep_handles_multiple_queens(tmp_path: Path) -> None:
    _seed(tmp_path, "alpha", "s_a", "in_progress")
    _seed(tmp_path, "beta", "s_b", "in_progress")
    _seed(tmp_path, "gamma", "s_c", "done")
    cleaned = compaction_status.sweep_stale_in_progress(tmp_path)
    assert cleaned == 2


def test_sweep_skips_sessions_without_marker(tmp_path: Path) -> None:
    # Session dir exists but no compaction_status.json
    sd = tmp_path / "alpha" / "sessions" / "s_clean"
    sd.mkdir(parents=True)
    cleaned = compaction_status.sweep_stale_in_progress(tmp_path)
    assert cleaned == 0
    assert not (sd / "compaction_status.json").exists()
