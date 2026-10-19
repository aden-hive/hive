"""Tests for the per-colony bookkeeping store (colony.db) — the playbook run-log.

This is separate from the domain tracker; here we exercise the record/list
roundtrip against a temp DB path directly (no colony fork needed).
"""

from __future__ import annotations

from pathlib import Path

from framework.host.colony_db import list_playbook_runs, record_playbook_run


def test_record_and_list_roundtrip(tmp_path: Path):
    db = tmp_path / "colony.db"
    record_playbook_run(
        db,
        run_id="pb_1",
        name="enrich",
        status="done",
        dispatched=12,
        dead_lettered=2,
        result={"remaining": 0},
        logs=["round 1: 12 dispatched", "converged"],
    )
    runs = list_playbook_runs(db)
    assert len(runs) == 1
    row = runs[0]
    assert row["run_id"] == "pb_1"
    assert row["name"] == "enrich"
    assert row["status"] == "done"
    assert row["dispatched"] == 12
    assert row["dead_lettered"] == 2
    assert '"remaining": 0' in row["result_json"]
    assert "converged" in row["logs_json"]
    assert row["created_at"]


def test_error_run_records_message(tmp_path: Path):
    db = tmp_path / "colony.db"
    record_playbook_run(db, run_id="pb_err", name=None, status="error", error="boom")
    runs = list_playbook_runs(db)
    assert len(runs) == 1
    assert runs[0]["status"] == "error"
    assert runs[0]["error"] == "boom"
    assert runs[0]["dispatched"] == 0


def test_upsert_replaces_same_run_id(tmp_path: Path):
    db = tmp_path / "colony.db"
    record_playbook_run(db, run_id="pb_x", name="a", status="error", error="first")
    record_playbook_run(db, run_id="pb_x", name="a", status="done", dispatched=5)
    runs = list_playbook_runs(db)
    assert len(runs) == 1  # replaced, not duplicated
    assert runs[0]["status"] == "done"
    assert runs[0]["dispatched"] == 5


def test_list_empty_when_no_db(tmp_path: Path):
    assert list_playbook_runs(tmp_path / "nope.db") == []
