"""Janitor safety tests: guards, locks, config, one-time sweeps.

Covers the KEEP_ALWAYS assertion, kill switch, config/env precedence,
global-lock single-flight with stale takeover, leftover sweep, legacy
agents/ refusal when QUEENS_DIR lives inside it, and the orphan
message-index sweep.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from framework import config
from framework.config import RetentionConfig, get_retention_config
from framework.maintenance import janitor
from framework.maintenance.janitor import run_once
from framework.maintenance.retention import (
    DeleteDisposer,
    DryRunDisposer,
    Manifest,
    SafetyContext,
    assert_safe_target,
    iter_legacy_queen_sessions,
    parse_session_dir_ts,
    sweep_janitor_leftovers,
    sweep_orphan_message_index,
)

_DAY = 86400.0


def _cfg(**overrides) -> RetentionConfig:
    base = {"active_grace_hours": 0, "io_sleep_ms": 0, "mode": "delete"}
    base.update(overrides)
    return RetentionConfig(**base)


def test_parse_session_dir_ts() -> None:
    ts = parse_session_dir_ts("session_20260101_120000_deadbeef")
    assert ts is not None
    assert time.localtime(ts).tm_year == 2026
    assert parse_session_dir_ts("not_a_session") is None


def test_assert_safe_target_refuses_protected_and_escaping_paths() -> None:
    for name in ("memories", "credentials", "secrets", "charts"):
        with pytest.raises(ValueError):
            assert_safe_target(config.HIVE_HOME / name / "x.md")
    with pytest.raises(ValueError):
        assert_safe_target(Path("/etc/passwd"))
    # Traversal that resolves outside HIVE_HOME is refused too.
    with pytest.raises(ValueError):
        assert_safe_target(config.HIVE_HOME / ".." / "elsewhere")
    # Non-protected targets inside HIVE_HOME pass.
    assert_safe_target(config.HIVE_HOME / "event_logs" / "x.jsonl")


def test_kill_switch_blocks_run() -> None:
    cfg = _cfg(enabled=False)
    report = run_once(SafetyContext.for_offline(cfg), cfg, tiers={1}, execute=True)
    assert "disabled" in report.error
    assert report.targets == []


def test_retention_config_file_and_env_precedence(monkeypatch) -> None:
    config.HIVE_CONFIG_FILE.write_text(
        json.dumps({"retention": {"event_logs_days": 3, "mode": "delete", "enabled": True}}),
        encoding="utf-8",
    )
    cfg = get_retention_config()
    assert cfg.event_logs_days == 3
    assert cfg.mode == "delete"

    monkeypatch.setenv("HIVE_RETENTION_EVENT_LOGS_DAYS", "9")
    monkeypatch.setenv("HIVE_RETENTION_ENABLED", "0")
    cfg = get_retention_config()
    assert cfg.event_logs_days == 9, "env beats configuration.json"
    assert cfg.enabled is False

    # Wrong-typed file values are ignored.
    config.HIVE_CONFIG_FILE.write_text(
        json.dumps({"retention": {"event_logs_days": "soon", "enabled": 1}}),
        encoding="utf-8",
    )
    monkeypatch.delenv("HIVE_RETENTION_EVENT_LOGS_DAYS")
    monkeypatch.delenv("HIVE_RETENTION_ENABLED")
    cfg = get_retention_config()
    assert cfg.event_logs_days == 7
    assert cfg.enabled is True


def test_global_lock_single_flight_and_stale_takeover() -> None:
    cfg = _cfg()
    lock = janitor._global_lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text('{"pid": 1}', encoding="utf-8")

    report = run_once(SafetyContext.for_offline(cfg), cfg, tiers={1}, execute=True)
    assert "in progress" in report.error

    # Stale lock (older than the TTL) is taken over.
    old = time.time() - 3 * 3600
    os.utime(lock, (old, old))
    report = run_once(SafetyContext.for_offline(cfg), cfg, tiers={1}, execute=True)
    assert report.error == ""
    assert not lock.exists(), "lock released after the run"

    # Dry-run never contends for the lock.
    lock.write_text('{"pid": 1}', encoding="utf-8")
    report = run_once(SafetyContext.for_offline(cfg), cfg, tiers={1}, execute=False)
    assert report.error == ""


def test_leftover_sweep_removes_stale_residue_only() -> None:
    stale_tmp = config.HIVE_HOME / "queens" / "q" / "sessions" / "s" / "events.jsonl.janitor-tmp"
    stale_tmp.parent.mkdir(parents=True)
    stale_tmp.write_text("partial", encoding="utf-8")
    stale_trash = config.HIVE_HOME / "colonies" / "c" / "workers" / "w.jtrash-123"
    stale_trash.mkdir(parents=True)
    (stale_trash / "f").write_text("x", encoding="utf-8")
    old = time.time() - 2 * 3600
    for p in (stale_tmp, stale_trash, stale_trash / "f"):
        os.utime(p, (old, old))

    fresh_tmp = config.HIVE_HOME / "queens" / "q" / "sessions" / "s" / "other.janitor-tmp"
    fresh_tmp.write_text("in flight", encoding="utf-8")

    report = sweep_janitor_leftovers(Manifest())
    assert not stale_tmp.exists()
    assert not stale_trash.exists()
    assert fresh_tmp.exists(), "fresh residue may belong to a live run"
    assert report.files == 2


def test_legacy_pass_never_deletes_the_agents_tree() -> None:
    """HIVE_HOME/agents is live storage (v3 reuses it — see migrate_v3.py);
    the legacy pass must only apply per-session hygiene, never rmtree."""
    agents = config.HIVE_HOME / "agents"
    session = agents / "queens" / "q1" / "sessions" / "session_20250101_000000_deadbeef"
    (session / "conversations" / "parts").mkdir(parents=True)
    agent_def = agents / "x_rapid_replier"
    agent_def.mkdir()
    (agent_def / "profile.yaml").write_text("name: x", encoding="utf-8")
    old = time.time() - 90 * 86400
    for p in [session, *session.rglob("*")]:
        os.utime(p, (old, old))

    cfg = _cfg(queen_hygiene_days=30)
    run_once(SafetyContext.for_offline(cfg), cfg, tiers=set(), execute=True, include_legacy=True)

    assert agents.exists()
    assert agent_def.exists(), "agent definitions under agents/ are live, never touched"
    assert session.exists(), "legacy pass is hygiene-only; transcripts survive"
    # Only queen session dirs are even enumerated.
    assert list(iter_legacy_queen_sessions()) == [session]


def test_legacy_sessions_get_tier3_hygiene(monkeypatch) -> None:
    # Point QUEENS_DIR elsewhere so the legacy iterator is the only source.
    monkeypatch.setattr(config, "QUEENS_DIR", config.HIVE_HOME / "queens")
    session = config.HIVE_HOME / "agents" / "queens" / "q1" / "sessions" / "session_20250101_000000_deadbeef"
    (session / "conversations" / "parts").mkdir(parents=True)
    (session / "data").mkdir()
    (session / "data" / "orphan_9.txt").write_text("x" * 300, encoding="utf-8")
    events = [json.dumps({"type": "context_usage_updated", "data": {"full_request": {"m": "y" * 400}}}) for _ in range(3)] + [
        json.dumps({"type": "tool_call_completed", "data": {"result": "keep"}})
    ]
    (session / "events.jsonl").write_text("\n".join(events) + "\n", encoding="utf-8")
    old = time.time() - 90 * 86400
    for p in [session, *session.rglob("*")]:
        os.utime(p, (old, old))

    cfg = _cfg(queen_hygiene_days=30, events_rewrite_min_bytes=10)
    run_once(SafetyContext.for_offline(cfg), cfg, tiers=set(), execute=True, include_legacy=True)

    assert not (session / "data" / "orphan_9.txt").exists()
    kept = (session / "events.jsonl").read_text(encoding="utf-8")
    assert "context_usage_updated" not in kept
    assert "tool_call_completed" in kept
    assert (session / "conversations").exists()


def test_orphan_message_index_sweep() -> None:
    idx = config.HIVE_HOME / ".message_index"
    # Live: source events.jsonl exists (queens scope reads agents/queens).
    live_src = config.HIVE_HOME / "agents" / "queens" / "qa" / "sessions" / "s1"
    live_src.mkdir(parents=True)
    (live_src / "events.jsonl").write_text("{}", encoding="utf-8")
    # Orphan: no source session on disk.
    for scope, owner, session in (("queens", "qa", "s1"), ("queens", "qa", "s2"), ("colonies", "cb", "s3")):
        for tree in ("events", "data", "meta"):
            sub = idx / tree / scope / owner / session
            sub.mkdir(parents=True)
            (sub / "stub").write_text("x", encoding="utf-8")

    report = sweep_orphan_message_index(DeleteDisposer(), Manifest())
    assert (idx / "meta" / "queens" / "qa" / "s1").exists(), "live session kept"
    assert not (idx / "meta" / "queens" / "qa" / "s2").exists()
    assert not (idx / "events" / "queens" / "qa" / "s2").exists()
    assert not (idx / "meta" / "colonies" / "cb" / "s3").exists()
    assert report.files == 6  # 3 trees x 2 orphaned sessions

    # Dry-run variant reports without deleting.
    for tree in ("events", "data", "meta"):
        sub = idx / tree / "queens" / "qa" / "s4"
        sub.mkdir(parents=True)
        (sub / "stub").write_text("x", encoding="utf-8")
    report = sweep_orphan_message_index(DryRunDisposer(), Manifest())
    assert (idx / "meta" / "queens" / "qa" / "s4").exists()
    assert report.files == 3


def test_junk_detection_reports_but_never_deletes_without_flag() -> None:
    junk = config.HIVE_HOME / "os"
    junk.write_text("%!PS" + "x" * 100, encoding="utf-8")
    cfg = _cfg(junk_min_bytes=10)
    report = run_once(SafetyContext.for_offline(cfg), cfg, tiers=set(), execute=True)
    assert junk.exists(), "junk needs the explicit include_junk flag"
    junk_report = next(t for t in report.targets if t.name == "junk")
    assert junk_report.skipped == 1

    report = run_once(SafetyContext.for_offline(cfg), cfg, tiers=set(), execute=True, include_junk=True)
    assert not junk.exists()


def test_protected_toplevel_entries_never_appear_as_junk() -> None:
    (config.HIVE_HOME / "memories").mkdir()
    (config.HIVE_HOME / "memories" / "fact.md").write_text("x" * 200, encoding="utf-8")
    (config.HIVE_HOME / "charts").mkdir()
    (config.HIVE_HOME / "charts" / "c.png").write_text("x" * 200, encoding="utf-8")
    cfg = _cfg(junk_min_bytes=1)
    report = run_once(SafetyContext.for_offline(cfg), cfg, tiers=set(), execute=True, include_junk=True)
    assert (config.HIVE_HOME / "memories" / "fact.md").exists()
    assert (config.HIVE_HOME / "charts" / "c.png").exists()
    junk_report = next(t for t in report.targets if t.name == "junk")
    assert junk_report.files == 0


def test_report_and_manifest_written_every_run() -> None:
    cfg = _cfg()
    report = run_once(SafetyContext.for_offline(cfg), cfg, tiers={1}, execute=False)
    assert Path(report.manifest_path).exists() or report.manifest_path == ""
    saved = janitor.load_last_report()
    assert saved is not None
    assert saved["dry_run"] is True
    assert saved["tiers"] == [1]
