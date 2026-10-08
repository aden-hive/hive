"""Tier-2 janitor tests: finished-worker deep-clean.

Covers the tombstone-first ordering, keep-set (meta.json/tasks.json),
stray-file removal, message-index co-deletion, endpoint compatibility
(_read_worker_from_disk / _read_worker_conversation), idempotence,
crash-resume convergence, and archive mode round-trip.
"""

from __future__ import annotations

import json
import os
import sys
import tarfile
import time
from pathlib import Path

import pytest

from framework import config
from framework.config import RetentionConfig
from framework.maintenance.janitor import run_once
from framework.maintenance.retention import (
    DeleteDisposer,
    Manifest,
    SafetyContext,
    deep_clean_worker,
)
from framework.server.routes_colony_workers import (
    _read_worker_conversation,
    _read_worker_from_disk,
)

_DAY = 86400.0
_WID = "session_20250101_120000_deadbeef"


def _age_tree(root: Path, days: float) -> None:
    old = time.time() - days * _DAY
    for p in [root, *root.rglob("*")]:
        os.utime(p, (old, old))


def _build_worker(colony: str = "c1", wid: str = _WID, age_days: float = 30.0) -> Path:
    wdir = config.COLONIES_DIR / colony / "workers" / wid
    (wdir / "conversations" / "parts").mkdir(parents=True)
    (wdir / "data").mkdir()
    (wdir / "meta.json").write_text(
        json.dumps(
            {
                "worker_id": wid,
                "queen_session_id": "session_20250101_110000_beefbeef",
                "colony_id": colony,
                "task": "do the thing",
                "profile_name": "researcher",
            }
        ),
        encoding="utf-8",
    )
    (wdir / "tasks.json").write_text('{"tasks": []}', encoding="utf-8")
    (wdir / "reminder_state.json").write_text('{"turns_total": 3}', encoding="utf-8")
    (wdir / "os").write_text("%!PS-Adobe-3.0 stray junk", encoding="utf-8")
    parts = wdir / "conversations" / "parts"
    (parts / "0000000001.json").write_text(json.dumps({"seq": 1, "role": "user", "content": "task"}), encoding="utf-8")
    (parts / "0000000002.json").write_text(
        json.dumps({"seq": 2, "role": "assistant", "content": "working on it"}),
        encoding="utf-8",
    )
    (parts / "0000000003.json").write_text(
        json.dumps({"seq": 3, "role": "tool", "content": "result", "tool_use_id": "call_1"}),
        encoding="utf-8",
    )
    (parts / "0000000004.json").write_text(
        json.dumps({"seq": 4, "role": "assistant", "content": "final summary of the work"}),
        encoding="utf-8",
    )
    (wdir / "conversations" / "cursor.json").write_text('{"next_seq": 5}', encoding="utf-8")
    (wdir / "data" / "web_scrape_1.txt").write_text("x" * 500, encoding="utf-8")
    # Message-index copies keyed by the worker session id.
    for tree in ("events", "data", "meta"):
        sub = config.HIVE_HOME / ".message_index" / tree / "colonies" / colony / wid
        sub.mkdir(parents=True)
        (sub / "stub.txt").write_text("copy", encoding="utf-8")
    _age_tree(wdir, age_days)
    return wdir


def _cfg(**overrides) -> RetentionConfig:
    base = {"active_grace_hours": 0, "worker_deep_clean_days": 14, "io_sleep_ms": 0, "mode": "delete"}
    base.update(overrides)
    return RetentionConfig(**base)


def test_deep_clean_end_to_end() -> None:
    wdir = _build_worker()
    cfg = _cfg()
    report = run_once(SafetyContext.for_offline(cfg), cfg, tiers={2}, execute=True)

    assert not (wdir / "conversations").exists()
    assert not (wdir / "data").exists()
    assert not (wdir / "reminder_state.json").exists()
    assert not (wdir / "os").exists(), "stray session-root files are removed"
    assert (wdir / "meta.json").exists()
    assert (wdir / "tasks.json").exists()

    tombstone = json.loads((wdir / "result.json").read_text(encoding="utf-8"))
    assert tombstone["status"] == "completed"
    assert tombstone["summary"] == "final summary of the work"
    assert "_janitor" in tombstone

    for tree in ("events", "data", "meta"):
        assert not (config.HIVE_HOME / ".message_index" / tree / "colonies" / "c1" / _WID).exists()

    tier2 = next(t for t in report.targets if t.name == "worker_deep_clean")
    assert tier2.bytes_freed > 0
    assert report.manifest_path and Path(report.manifest_path).exists()


def test_endpoints_render_after_deep_clean() -> None:
    wdir = _build_worker()
    cfg = _cfg()
    run_once(SafetyContext.for_offline(cfg), cfg, tiers={2}, execute=True)

    detail = _read_worker_from_disk(_WID, wdir)
    assert detail["status"] == "historical"
    assert detail["task"] == "do the thing"
    assert detail["result"]["summary"] == "final summary of the work"

    convo = _read_worker_conversation(wdir)
    assert convo == {"messages": [], "total": 0, "truncated": False}


def test_deep_clean_is_idempotent() -> None:
    wdir = _build_worker()
    cfg = _cfg()
    run_once(SafetyContext.for_offline(cfg), cfg, tiers={2}, execute=True)
    first = json.loads((wdir / "result.json").read_text(encoding="utf-8"))

    report2 = run_once(SafetyContext.for_offline(cfg), cfg, tiers={2}, execute=True)
    second = json.loads((wdir / "result.json").read_text(encoding="utf-8"))
    assert first == second, "existing tombstone is never rewritten"
    tier2 = next(t for t in report2.targets if t.name == "worker_deep_clean")
    assert tier2.bytes_freed == 0


def test_crash_resume_converges() -> None:
    """Tombstone already written, dirs still present (crash mid-clean)."""
    wdir = _build_worker()
    tombstone = {"status": "completed", "summary": "s", "_janitor": {"pruned_at": "x"}}
    (wdir / "result.json").write_text(json.dumps(tombstone), encoding="utf-8")
    _age_tree(wdir, 30)

    report = deep_clean_worker("c1", _WID, wdir, disposer=DeleteDisposer(), manifest=Manifest())
    assert not (wdir / "conversations").exists()
    assert not (wdir / "data").exists()
    assert json.loads((wdir / "result.json").read_text(encoding="utf-8")) == tombstone
    assert report.bytes_freed > 0


def test_recent_worker_is_skipped() -> None:
    wdir = _build_worker(age_days=1.0)
    cfg = _cfg()  # window 14d
    report = run_once(SafetyContext.for_offline(cfg), cfg, tiers={2}, execute=True)
    assert (wdir / "conversations").exists()
    tier2 = next(t for t in report.targets if t.name == "worker_deep_clean")
    assert tier2.skipped == 1


def test_worker_of_live_queen_is_skipped() -> None:
    wdir = _build_worker()
    cfg = _cfg()
    safety = SafetyContext(
        protected_session_ids=frozenset({"session_20250101_110000_beefbeef"}),
        live_session_dirs=frozenset(),
        grace_seconds=0,
    )
    run_once(safety, cfg, tiers={2}, execute=True)
    assert (wdir / "conversations").exists(), "spawning queen live => worker untouched"


def test_dry_run_changes_nothing_and_lists_candidates() -> None:
    wdir = _build_worker()
    cfg = _cfg()
    before = sorted(str(p) for p in wdir.rglob("*"))
    report = run_once(SafetyContext.for_offline(cfg), cfg, tiers={2}, execute=False)
    after = sorted(str(p) for p in wdir.rglob("*"))
    assert before == after
    assert not (wdir / "result.json").exists()
    tier2 = next(t for t in report.targets if t.name == "worker_deep_clean")
    assert tier2.bytes_freed > 0, "dry run still measures would-free bytes"
    manifest_lines = Path(report.manifest_path).read_text(encoding="utf-8").splitlines()
    assert any('"outcome": "candidate"' in line or '"candidate"' in line for line in manifest_lines)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "Janitor archive dispose renames then rmtrees the source dir; on Windows "
        "the source can survive due to file-handle release timing after tarfile.add "
        "(dispose uses ignore_errors=True). Tracked as a separate Windows hardening item."
    ),
)
def test_archive_mode_round_trip(tmp_path: Path) -> None:
    wdir = _build_worker()
    original_part = (wdir / "conversations" / "parts" / "0000000004.json").read_text(encoding="utf-8")
    cfg = _cfg(mode="archive")
    report = run_once(SafetyContext.for_offline(cfg), cfg, tiers={2}, execute=True)

    assert not (wdir / "conversations").exists()
    assert report.archive_path, "archive mode records the run's archive dir"
    archive_dir = Path(report.archive_path)
    assert archive_dir.is_dir()
    tarballs = sorted(archive_dir.glob("*.tar.gz"))
    assert tarballs, "one durable tarball per disposal target"
    assert not list(archive_dir.glob("*.tmp")), "no torn in-flight archives left"

    extract_to = tmp_path / "restore"
    names: list[str] = []
    for tb in tarballs:
        with tarfile.open(tb) as tar:
            names.extend(tar.getnames())
            tar.extractall(extract_to)
    # Member paths are relative to HIVE_HOME so untarring reproduces layout.
    rel = f"colonies/c1/workers/{_WID}/conversations"
    assert any(n.startswith(rel) for n in names)
    restored = extract_to / "colonies" / "c1" / "workers" / _WID / "conversations" / "parts" / "0000000004.json"
    assert restored.read_text(encoding="utf-8") == original_part


def test_archive_failure_keeps_source(monkeypatch) -> None:
    """A failed archive must never let the source be deleted."""
    from framework.maintenance.archive import ArchiveDisposer

    wdir = _build_worker()
    disposer = ArchiveDisposer()
    monkeypatch.setattr(ArchiveDisposer, "_archive_one", lambda self, path: (_ for _ in ()).throw(OSError("disk full")))
    import pytest

    with pytest.raises(OSError):
        disposer.dispose_dir(wdir / "conversations")
    assert (wdir / "conversations" / "parts" / "0000000004.json").exists()
