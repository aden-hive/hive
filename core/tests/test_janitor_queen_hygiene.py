"""Tier-3 janitor tests: cold queen session hygiene.

Covers orphan-spillover reference protection (all three placeholder
formats + cursor.json outputs), events.jsonl rewrite semantics
(drop telemetry, strip legacy full_request, preserve corrupt lines and
order, atomic tmp+replace, min-size and min-savings gates), the
message-index force-reset, and the .pruned.json marker.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from framework import config
from framework.config import RetentionConfig
from framework.maintenance.janitor import run_once
from framework.maintenance.retention import (
    DeleteDisposer,
    Manifest,
    SafetyContext,
    find_orphan_spillovers,
    rewrite_events_jsonl,
)

_DAY = 86400.0
_SID = "session_20250101_090000_cafecafe"


def _age_tree(root: Path, days: float) -> None:
    old = time.time() - days * _DAY
    for p in [root, *root.rglob("*")]:
        os.utime(p, (old, old))


def _event(evt_type: str, **data) -> str:
    return json.dumps({"type": evt_type, "stream_id": "queen", "data": data})


def _build_session(queen: str = "q1", sid: str = _SID, age_days: float = 60.0) -> Path:
    sdir = config.QUEENS_DIR / queen / "sessions" / sid
    parts = sdir / "conversations" / "parts"
    parts.mkdir(parents=True)
    data_dir = sdir / "data"
    (data_dir / "attachments").mkdir(parents=True)

    # Live parts referencing spillovers in every known placeholder format.
    (parts / "0000000001.json").write_text(
        json.dumps(
            {
                "seq": 1,
                "role": "tool",
                "content": f"Full result at: {data_dir}/terminal_exec_15.txt (grep it)",
            }
        ),
        encoding="utf-8",
    )
    (parts / "0000000002.json").write_text(
        json.dumps({"seq": 2, "role": "tool", "content": "Old result [Saved to 'web_scrape_3.txt']"}),
        encoding="utf-8",
    )
    (parts / "0000000003.json").write_text(
        json.dumps(
            {
                "seq": 3,
                "role": "user",
                "content": "Previous conversation saved at conversation_1.md",
            }
        ),
        encoding="utf-8",
    )
    (sdir / "conversations" / "cursor.json").write_text(
        json.dumps({"next_seq": 4, "outputs": {"report": f"Output saved at: {data_dir}/output_report.json"}}),
        encoding="utf-8",
    )

    # Spillover files: three referenced, one orphaned, plus protected kinds.
    (data_dir / "terminal_exec_15.txt").write_text("kept-abs-path", encoding="utf-8")
    (data_dir / "web_scrape_3.txt").write_text("kept-legacy-format", encoding="utf-8")
    (data_dir / "output_report.json").write_text("kept-cursor-ref", encoding="utf-8")
    (data_dir / "browser_snapshot_7.txt").write_text("o" * 400, encoding="utf-8")  # orphan
    (data_dir / "conversation_1.md").write_text("handoff transcript", encoding="utf-8")
    (data_dir / "attachments" / "upload.pdf").write_text("user upload", encoding="utf-8")

    # events.jsonl: telemetry + real events + one corrupt line.
    lines = [
        _event("tool_call_started", tool_name="web_scrape"),
        _event("context_usage_updated", usage_pct=10, full_request={"messages": ["m" * 2000]}),
        _event("tool_call_completed", tool_name="web_scrape", result="r" * 50),
        "THIS IS NOT JSON {",
        _event("context_usage_updated", usage_pct=55, full_request={"messages": ["m" * 2000]}),
        _event("client_output_delta", text="hello"),
    ]
    (sdir / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Message-index cache for this session (queens scope).
    for tree in ("events", "data"):
        sub = config.HIVE_HOME / ".message_index" / tree / "queens" / queen / sid
        sub.mkdir(parents=True)
        (sub / "000001.tool.txt").write_text("indexed copy", encoding="utf-8")
    meta = config.HIVE_HOME / ".message_index" / "meta" / "queens" / queen / sid
    meta.mkdir(parents=True)
    (meta / "cursor.json").write_text('{"events_byte_offset": 10, "next_ordinal": 2}', encoding="utf-8")
    (meta / "data_map.json").write_text("{}", encoding="utf-8")

    _age_tree(sdir, age_days)
    return sdir


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


def test_orphan_detection_protects_all_reference_formats() -> None:
    sdir = _build_session()
    orphans = find_orphan_spillovers(sdir, min_age_days=30, now=time.time())
    assert [p.name for p in orphans] == ["browser_snapshot_7.txt"]


def test_queen_hygiene_end_to_end() -> None:
    sdir = _build_session()
    cfg = _cfg()
    report = run_once(SafetyContext.for_offline(cfg), cfg, tiers={3}, execute=True)

    data_dir = sdir / "data"
    assert not (data_dir / "browser_snapshot_7.txt").exists()
    assert (data_dir / "terminal_exec_15.txt").exists()
    assert (data_dir / "web_scrape_3.txt").exists()
    assert (data_dir / "output_report.json").exists()
    assert (data_dir / "conversation_1.md").exists()
    assert (data_dir / "attachments" / "upload.pdf").exists()

    remaining = (sdir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    types = []
    for line in remaining:
        try:
            types.append(json.loads(line)["type"])
        except (json.JSONDecodeError, KeyError):
            types.append("<corrupt>")
    assert types == ["tool_call_started", "tool_call_completed", "<corrupt>", "client_output_delta"]
    assert "THIS IS NOT JSON {" in remaining, "corrupt lines preserved verbatim"
    assert not list(sdir.glob("*.janitor-tmp"))
    assert not (sdir / ".janitor.lock").exists()
    assert (sdir / ".pruned.json").exists()

    # Index cache force-reset for the rewritten session.
    idx = config.HIVE_HOME / ".message_index"
    assert not (idx / "events" / "queens" / "q1" / _SID).exists()
    assert not (idx / "data" / "queens" / "q1" / _SID).exists()
    assert not (idx / "meta" / "queens" / "q1" / _SID / "cursor.json").exists()

    tier3 = next(t for t in report.targets if t.name == "queen_hygiene")
    assert tier3.bytes_freed > 0


def test_rewrite_strips_legacy_full_request_from_kept_lines() -> None:
    sdir = _build_session()
    # A kept event type that still carries a legacy full_request payload.
    events = sdir / "events.jsonl"
    lines = events.read_text(encoding="utf-8").splitlines()
    lines.append(_event("llm_turn_complete", iteration=1, full_request={"messages": ["x" * 3000]}))
    events.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _age_tree(sdir, 60)

    rewrite_events_jsonl(events, min_bytes=10, disposer=DeleteDisposer(), manifest=Manifest())
    for line in events.read_text(encoding="utf-8").splitlines():
        assert "full_request" not in line
    kept_types = [json.loads(ln)["type"] for ln in events.read_text(encoding="utf-8").splitlines() if ln.startswith("{")]
    assert "llm_turn_complete" in kept_types


def test_rewrite_skips_small_files_and_low_savings() -> None:
    sdir = _build_session()
    events = sdir / "events.jsonl"
    original = events.read_text(encoding="utf-8")

    # Below min_bytes: untouched.
    assert rewrite_events_jsonl(events, min_bytes=10**9, disposer=DeleteDisposer(), manifest=Manifest()) == 0
    assert events.read_text(encoding="utf-8") == original

    # Savings under 10%: untouched. Build a file where telemetry is tiny.
    big = [_event("tool_call_completed", result="k" * 5000) for _ in range(10)]
    big.append(json.dumps({"type": "context_usage_updated", "data": {"usage_pct": 1}}))
    events.write_text("\n".join(big) + "\n", encoding="utf-8")
    before = events.read_text(encoding="utf-8")
    assert rewrite_events_jsonl(events, min_bytes=10, disposer=DeleteDisposer(), manifest=Manifest()) == 0
    assert events.read_text(encoding="utf-8") == before


def test_active_session_untouched() -> None:
    sdir = _build_session()
    cfg = _cfg()
    safety = SafetyContext(
        protected_session_ids=frozenset({_SID}),
        live_session_dirs=frozenset(),
        grace_seconds=0,
    )
    report = run_once(safety, cfg, tiers={3}, execute=True)
    assert (sdir / "data" / "browser_snapshot_7.txt").exists()
    assert ".pruned.json" not in [p.name for p in sdir.iterdir()]
    tier3 = next(t for t in report.targets if t.name == "queen_hygiene")
    assert tier3.skipped >= 1


def test_recently_active_session_untouched() -> None:
    sdir = _build_session(age_days=60)
    # Fresh cursor mtime simulates recent activity despite an old dir name.
    os.utime(sdir / "conversations" / "cursor.json", None)
    cfg = _cfg()
    run_once(SafetyContext.for_offline(cfg), cfg, tiers={3}, execute=True)
    assert (sdir / "data" / "browser_snapshot_7.txt").exists()


def test_dry_run_changes_nothing() -> None:
    sdir = _build_session()
    cfg = _cfg()
    before = {str(p): (p.stat().st_size if p.is_file() else -1) for p in sdir.rglob("*")}
    report = run_once(SafetyContext.for_offline(cfg), cfg, tiers={3}, execute=False)
    after = {str(p): (p.stat().st_size if p.is_file() else -1) for p in sdir.rglob("*")}
    assert before == after
    tier3 = next(t for t in report.targets if t.name == "queen_hygiene")
    assert tier3.bytes_freed > 0


def test_colony_overseer_sessions_are_covered() -> None:
    sid = "session_20250101_080000_feedfeed"
    sdir = config.COLONIES_DIR / "c9" / "queens" / "qz" / "sessions" / sid
    (sdir / "conversations" / "parts").mkdir(parents=True)
    (sdir / "data").mkdir()
    (sdir / "data" / "orphan_1.txt").write_text("x" * 200, encoding="utf-8")
    lines = [_event("context_usage_updated", full_request={"m": "y" * 500}) for _ in range(3)]
    lines.append(_event("tool_call_completed", result="keep"))
    (sdir / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    _age_tree(sdir, 90)

    cfg = _cfg()
    run_once(SafetyContext.for_offline(cfg), cfg, tiers={3}, execute=True)
    assert not (sdir / "data" / "orphan_1.txt").exists()
    kept = (sdir / "events.jsonl").read_text(encoding="utf-8")
    assert "context_usage_updated" not in kept
    assert "tool_call_completed" in kept
