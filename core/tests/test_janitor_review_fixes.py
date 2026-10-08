"""Regression tests for defects found in the janitor adversarial review.

Each test pins one confirmed finding:
- spillover extractors must match the CURRENT "Full result at:" header
  (missing it strands the only copy of a spilled tool result);
- the orphan-scan corpus fails CLOSED on read errors;
- the post-lock re-check must not be short-circuited by the janitor's
  own session lock, and must see a refreshed live-set;
- offline execute of destructive tiers is refused while a live server
  owns HIVE_HOME (server marker, not port probe);
- a failing disposer setup must not leak the 2h global lock.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from framework import config
from framework.config import RetentionConfig
from framework.maintenance import janitor
from framework.maintenance.janitor import run_once
from framework.maintenance.retention import (
    DeleteDisposer,
    Manifest,
    SafetyContext,
    find_orphan_spillovers,
    prune_queen_session,
)

_DAY = 86400.0
_SID = "session_20250101_070000_beadbead"


def _cfg(**overrides) -> RetentionConfig:
    base = {
        "active_grace_hours": 0,
        "queen_hygiene_days": 30,
        "events_rewrite_min_bytes": 10,
        "io_sleep_ms": 0,
        "mode": "delete",
    }
    base.update(overrides)
    return RetentionConfig(**base)


def _age_tree(root: Path, days: float) -> None:
    old = time.time() - days * _DAY
    for p in [root, *root.rglob("*")]:
        os.utime(p, (old, old))


def _build_session(sid: str = _SID) -> Path:
    sdir = config.QUEENS_DIR / "qx" / "sessions" / sid
    (sdir / "conversations" / "parts").mkdir(parents=True)
    (sdir / "data").mkdir()
    lines = [json.dumps({"type": "context_usage_updated", "data": {"full_request": {"m": "z" * 500}}}) for _ in range(3)] + [
        json.dumps({"type": "tool_call_completed", "data": {"result": "keep"}})
    ]
    (sdir / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _age_tree(sdir, 60)
    return sdir


# ---------------------------------------------------------------------------
# Spillover extractors — every historical header format must resolve.
# ---------------------------------------------------------------------------


def test_extractors_match_all_header_formats() -> None:
    from framework.agent_loop.conversation import _extract_spillover_filename
    from framework.agent_loop.internals.compaction import _extract_spillover_filename_inline

    current = (
        "Tool `terminal_exec` returned 50,893 characters (too large for context). "
        "Full result at: /h/session/data/terminal_exec_15.txt\n"
        'For targeted lookup, run `grep -nE "<pattern>" "/h/session/data/terminal_exec_15.txt"`.'
    )
    micro = "Old tool result (44,754 chars) at /h/session/data/web_scrape_3.txt. Use terminal_rg."
    prose = "Full result saved at: /h/session/data/pdf_read_2.txt"
    legacy = "Result too big [Saved to 'browser_html_9.txt']"

    for extractor in (_extract_spillover_filename, _extract_spillover_filename_inline):
        assert extractor(current) == "/h/session/data/terminal_exec_15.txt", extractor.__name__
        assert extractor(micro) == "/h/session/data/web_scrape_3.txt", extractor.__name__
        assert extractor(prose) == "/h/session/data/pdf_read_2.txt", extractor.__name__
        assert extractor(legacy) == "browser_html_9.txt", extractor.__name__


def test_orphan_scan_protects_current_header_after_prune_placeholder() -> None:
    """A part whose content is the CURRENT truncate header protects its file,
    and tool_calls arguments count as references (raw-JSON corpus)."""
    sdir = _build_session()
    data_dir = sdir / "data"
    (data_dir / "terminal_exec_15.txt").write_text("big", encoding="utf-8")
    (data_dir / "greppable_7.txt").write_text("big", encoding="utf-8")
    parts = sdir / "conversations" / "parts"
    (parts / "0000000001.json").write_text(
        json.dumps({"seq": 1, "role": "tool", "content": "... Full result at: " + str(data_dir / "terminal_exec_15.txt")}),
        encoding="utf-8",
    )
    # Reference living only in an assistant tool_calls arguments blob.
    (parts / "0000000002.json").write_text(
        json.dumps(
            {
                "seq": 2,
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {"name": "terminal_exec", "arguments": '{"command": "grep -n foo ' + str(data_dir / "greppable_7.txt") + '"}'},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    _age_tree(sdir, 60)
    orphans = find_orphan_spillovers(sdir, min_age_days=30, now=time.time())
    assert orphans == []


def test_orphan_scan_fails_closed_on_read_error(monkeypatch) -> None:
    sdir = _build_session()
    (sdir / "data" / "would_be_orphan_1.txt").write_text("x" * 100, encoding="utf-8")
    part = sdir / "conversations" / "parts" / "0000000001.json"
    part.write_text(json.dumps({"seq": 1, "role": "tool", "content": "hi"}), encoding="utf-8")
    _age_tree(sdir, 60)

    real_read_text = Path.read_text

    def flaky_read_text(self, *args, **kwargs):
        if self.name == "0000000001.json":
            raise OSError("transient I/O error")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)
    assert find_orphan_spillovers(sdir, min_age_days=30, now=time.time()) == []


# ---------------------------------------------------------------------------
# Post-lock re-check: own lock must not short-circuit; refresher is honored.
# ---------------------------------------------------------------------------


def test_own_lock_does_not_mask_liveness_recheck() -> None:
    _cfg()
    sdir = _build_session()
    (sdir / ".janitor.lock").write_text('{"pid": 1}', encoding="utf-8")
    safety = SafetyContext(
        protected_session_ids=frozenset({_SID}),  # session became live
        live_session_dirs=frozenset(),
        grace_seconds=0,
    )
    ok, reason = safety.is_safe_to_prune(sdir, min_age_days=30, ignore_janitor_lock=True)
    assert not ok and "live" in reason, "liveness must be evaluated even under our own lock"


def test_refresher_blocks_mid_run_resume() -> None:
    """Initial snapshot says cold; the refreshed set (simulating a resume
    during the run) marks the session live — the rewrite must be skipped."""
    cfg = _cfg()
    sdir = _build_session()
    events_before = (sdir / "events.jsonl").read_text(encoding="utf-8")
    safety = SafetyContext(
        protected_session_ids=frozenset(),
        live_session_dirs=frozenset(),
        grace_seconds=0,
        refresher=lambda: (frozenset({_SID}), frozenset()),
    )
    report = prune_queen_session(sdir, cfg=cfg, safety=safety, disposer=DeleteDisposer(), manifest=Manifest())
    assert (sdir / "events.jsonl").read_text(encoding="utf-8") == events_before
    assert report.skipped == 1
    assert not (sdir / ".janitor.lock").exists()


# ---------------------------------------------------------------------------
# Offline destructive execute refused while a live server owns HIVE_HOME.
# ---------------------------------------------------------------------------


def test_offline_execute_refused_when_server_marker_live() -> None:
    janitor.write_server_marker(port=1234)
    # Marker must name a DIFFERENT live pid. Use the parent pid: it is alive
    # for the duration of the test and distinct from os.getpid(), and it is
    # queryable on every platform (pid 1 is not a live/queryable process on
    # Windows, so hardcoding it made this test Linux-only).
    marker = janitor.server_marker_path()
    marker.write_text(json.dumps({"pid": os.getppid(), "started_at": time.time()}), encoding="utf-8")

    cfg = _cfg()
    report = run_once(SafetyContext.for_offline(cfg), cfg, tiers={2, 3}, execute=True)
    assert "live runtime owns this HIVE_HOME" in report.error

    # Tier 1 alone stays allowed (debug logs only, open-handle guarded).
    report = run_once(SafetyContext.for_offline(cfg), cfg, tiers={1}, execute=True)
    assert report.error == ""

    # Dry-run of destructive tiers is also fine.
    report = run_once(SafetyContext.for_offline(cfg), cfg, tiers={2, 3}, execute=False)
    assert report.error == ""

    # A dead pid unblocks execution.
    marker.write_text(json.dumps({"pid": 2**22 + 12345, "started_at": time.time()}), encoding="utf-8")
    report = run_once(SafetyContext.for_offline(cfg), cfg, tiers={2, 3}, execute=True)
    assert report.error == ""


def test_server_marker_lifecycle() -> None:
    janitor.write_server_marker(port=8787)
    data = json.loads(janitor.server_marker_path().read_text(encoding="utf-8"))
    assert data["pid"] == os.getpid()
    # Own pid never counts as a foreign live server.
    assert not janitor.live_server_owns_hive_home()
    janitor.clear_server_marker()
    assert not janitor.server_marker_path().exists()


# ---------------------------------------------------------------------------
# Global lock must not leak when disposer setup fails.
# ---------------------------------------------------------------------------


def test_global_lock_not_leaked_on_disposer_setup_failure(monkeypatch) -> None:
    cfg = _cfg(mode="archive")

    def boom(cfg_, execute):
        raise OSError("archive dir on read-only fs")

    monkeypatch.setattr(janitor, "_build_disposer", boom)
    report = run_once(SafetyContext.for_offline(cfg), cfg, tiers={2}, execute=True)
    assert "disposer setup failed" in report.error
    assert not janitor._global_lock_path().exists(), "no 2h lockout left behind"
    assert janitor.load_last_report() is not None, "failure still produces a report"

    # And a follow-up run works immediately.
    monkeypatch.undo()
    report = run_once(SafetyContext.for_offline(cfg), cfg, tiers={2}, execute=True)
    assert report.error == ""
