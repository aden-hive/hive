"""Tier-1 janitor tests: age-out of flat debug stores.

Covers filename-timestamp aging (event_logs/llm_logs/compaction_log/
tool-artifacts), the keep-newest and open-handle guards, mtime fallback
for unparseable names, and dry-run byte accounting.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from framework import config
from framework.maintenance.retention import (
    DeleteDisposer,
    DryRunDisposer,
    Manifest,
    _tier1_file_ts,
    prune_aged_dir,
)

_DAY = 86400.0


def _write_aged(path: Path, body: str, age_days: float) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    old = time.time() - age_days * _DAY
    os.utime(path, (old, old))
    return path


def _log_name(age_days: float) -> str:
    ts = time.localtime(time.time() - age_days * _DAY)
    return time.strftime("%Y%m%d_%H%M%S", ts) + ".jsonl"


def test_tier1_filename_ts_parsers() -> None:
    assert _tier1_file_ts("20260515_131452.jsonl") is not None
    assert _tier1_file_ts("20260429T002854_346307_queen.md") is not None
    ts = _tier1_file_ts("browser_snapshot_1783031564665_tab2.txt")
    assert ts is not None and abs(ts - 1783031564.665) < 1
    assert _tier1_file_ts("random-name.log") is None


def test_prune_aged_dir_deletes_old_keeps_new_and_newest() -> None:
    d = config.HIVE_HOME / "event_logs"
    old_a = _write_aged(d / _log_name(30), "x" * 100, 30)
    old_b = _write_aged(d / _log_name(20), "y" * 50, 20)
    fresh = _write_aged(d / _log_name(1), "z", 1)

    report = prune_aged_dir(
        d,
        target="event_logs",
        max_age_days=7,
        disposer=DeleteDisposer(),
        manifest=Manifest(),
        keep_newest=1,
    )
    assert not old_a.exists()
    assert not old_b.exists()
    assert fresh.exists()
    assert report.files == 2
    assert report.bytes_freed == 150


def test_prune_aged_dir_keep_newest_survives_even_if_old() -> None:
    # event_logs and llm_logs keep their newest file: a live writer holds
    # it open, and the offline CLI janitor has no process_start_ts guard.
    d = config.HIVE_HOME / "event_logs"
    only = _write_aged(d / _log_name(90), "x", 90)
    prune_aged_dir(
        d,
        target="event_logs",
        max_age_days=7,
        disposer=DeleteDisposer(),
        manifest=Manifest(),
        keep_newest=1,
    )
    assert only.exists(), "the newest file per dir is never deleted (may be held open)"


def test_prune_aged_dir_skips_files_written_since_process_start() -> None:
    d = config.HIVE_HOME / "event_logs"
    # Filename says ancient, but mtime is now (an open handle re-writing it).
    held_open = d / _log_name(60)
    held_open.parent.mkdir(parents=True, exist_ok=True)
    held_open.write_text("live", encoding="utf-8")
    decoy = _write_aged(d / _log_name(59), "old", 59)

    prune_aged_dir(
        d,
        target="event_logs",
        max_age_days=7,
        disposer=DeleteDisposer(),
        manifest=Manifest(),
        keep_newest=0,
        process_start_ts=time.time() - 3600,
    )
    assert held_open.exists()
    assert not decoy.exists()


def test_prune_aged_dir_mtime_fallback_for_unparseable_names() -> None:
    d = config.HIVE_HOME / "logs"
    rotated_old = _write_aged(d / "sentinel.log.3", "aaa", 45)
    rotated_new = _write_aged(d / "sentinel.log.1", "bbb", 2)
    live = _write_aged(d / "sentinel.log", "ccc", 0)

    prune_aged_dir(
        d,
        target="logs",
        max_age_days=30,
        disposer=DeleteDisposer(),
        manifest=Manifest(),
        keep_newest=2,
    )
    assert not rotated_old.exists()
    assert rotated_new.exists()
    assert live.exists()


def test_prune_aged_dir_dry_run_reports_without_deleting() -> None:
    d = config.HIVE_HOME / "compaction_log"
    old = _write_aged(d / "20250101T000000_000001_queen.md", "m" * 64, 200)
    manifest = Manifest()
    report = prune_aged_dir(
        d,
        target="compaction_log",
        max_age_days=7,
        disposer=DryRunDisposer(),
        manifest=manifest,
        keep_newest=0,
    )
    assert old.exists()
    assert report.bytes_freed == 64
    assert len(manifest.items) == 1
    assert manifest.items[0].outcome == "candidate"
    assert manifest.items[0].bytes == 64


def test_prune_aged_dir_missing_dir_is_noop() -> None:
    report = prune_aged_dir(
        config.HIVE_HOME / "does_not_exist",
        target="event_logs",
        max_age_days=7,
        disposer=DeleteDisposer(),
        manifest=Manifest(),
    )
    assert report.files == 0 and report.bytes_freed == 0
