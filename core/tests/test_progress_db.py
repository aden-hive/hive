"""Tests for framework.host.progress_db — per-colony task queue."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from framework.host.progress_db import (
    SCHEMA_VERSION,
    enqueue_task,
    ensure_all_colony_dbs,
    ensure_progress_db,
    reclaim_stale,
    seed_tasks,
)

# ----------------------------------------------------------------------
# Schema / init
# ----------------------------------------------------------------------


def test_ensure_progress_db_fresh(tmp_path: Path) -> None:
    colony = tmp_path / "c"
    db_path = ensure_progress_db(colony)
    assert db_path.exists()
    assert db_path.name == "progress.db"
    assert db_path.parent.name == "data"

    con = sqlite3.connect(str(db_path))
    try:
        assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert con.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"tasks", "steps", "sop_checklist", "colony_meta"}.issubset(tables)

        indexes = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        # Named indexes we declared
        assert "idx_tasks_claimable" in indexes
        assert "idx_steps_task_seq" in indexes
        assert "idx_sop_required_open" in indexes
        assert "idx_tasks_status" in indexes
    finally:
        con.close()


def test_ensure_progress_db_idempotent(tmp_path: Path) -> None:
    colony = tmp_path / "c"
    p1 = ensure_progress_db(colony)
    p2 = ensure_progress_db(colony)
    assert p1 == p2
    con = sqlite3.connect(str(p1))
    try:
        assert con.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        con.close()


def test_ensure_all_colony_dbs_backfill(tmp_path: Path) -> None:
    colonies_root = tmp_path / "colonies"
    (colonies_root / "alpha").mkdir(parents=True)
    (colonies_root / "beta").mkdir(parents=True)
    (colonies_root / "gamma_not_dir").touch()  # should be ignored

    initialized = ensure_all_colony_dbs(colonies_root)
    names = {p.parent.parent.name for p in initialized}
    assert names == {"alpha", "beta"}
    for p in initialized:
        assert p.exists()


def test_ensure_all_colony_dbs_missing_root(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent"
    assert ensure_all_colony_dbs(missing) == []


# ----------------------------------------------------------------------
# Seeding / enqueue
# ----------------------------------------------------------------------


def test_seed_tasks_basic(tmp_path: Path) -> None:
    db = ensure_progress_db(tmp_path / "c")
    ids = seed_tasks(
        db,
        [
            {
                "goal": "task one",
                "priority": 5,
                "payload": {"url": "https://example.com"},
                "steps": [
                    {"title": "open page"},
                    {"title": "extract data", "detail": "selector .content"},
                ],
                "sop_items": [
                    {"key": "captcha_handled", "description": "Verify no CAPTCHA blocks"},
                    {"key": "soft_hint", "description": "optional", "required": False},
                ],
            },
            {"goal": "task two"},
        ],
    )
    assert len(ids) == 2

    con = sqlite3.connect(str(db))
    try:
        rows = list(con.execute("SELECT id, goal, priority, status, source, payload FROM tasks ORDER BY goal"))
        assert len(rows) == 2
        assert rows[0][1] == "task one"
        assert rows[0][2] == 5
        assert rows[0][3] == "pending"
        assert rows[0][4] == "queen_create"
        assert '"url"' in rows[0][5]

        step_count = con.execute(
            "SELECT count(*) FROM steps WHERE task_id=?", (ids[0],)
        ).fetchone()[0]
        assert step_count == 2

        sop_rows = list(con.execute(
            "SELECT key, required FROM sop_checklist WHERE task_id=? ORDER BY key", (ids[0],)
        ))
        assert sop_rows == [("captcha_handled", 1), ("soft_hint", 0)]
    finally:
        con.close()


def test_seed_tasks_rejects_missing_goal(tmp_path: Path) -> None:
    db = ensure_progress_db(tmp_path / "c")
    with pytest.raises(ValueError):
        seed_tasks(db, [{"priority": 1}])


def test_seed_tasks_empty_is_noop(tmp_path: Path) -> None:
    db = ensure_progress_db(tmp_path / "c")
    assert seed_tasks(db, []) == []


def test_seed_tasks_rollback_on_partial_failure(tmp_path: Path) -> None:
    """A bad row mid-batch must roll back the whole transaction."""
    db = ensure_progress_db(tmp_path / "c")
    with pytest.raises(ValueError):
        seed_tasks(
            db,
            [
                {"goal": "good one"},
                {"priority": 1},  # missing goal -> boom
                {"goal": "never inserted"},
            ],
        )
    con = sqlite3.connect(str(db))
    try:
        count = con.execute("SELECT count(*) FROM tasks").fetchone()[0]
        assert count == 0
    finally:
        con.close()


def test_enqueue_task(tmp_path: Path) -> None:
    db = ensure_progress_db(tmp_path / "c")
    tid = enqueue_task(
        db,
        "appended",
        steps=[{"title": "s1"}],
        sop_items=[{"key": "k", "description": "d"}],
        priority=3,
    )
    assert tid

    con = sqlite3.connect(str(db))
    try:
        row = con.execute(
            "SELECT goal, priority, source FROM tasks WHERE id=?", (tid,)
        ).fetchone()
        assert row == ("appended", 3, "enqueue_tool")
        assert con.execute(
            "SELECT count(*) FROM steps WHERE task_id=?", (tid,)
        ).fetchone()[0] == 1
    finally:
        con.close()


def test_enqueue_task_custom_source(tmp_path: Path) -> None:
    """enqueue_task must accept a custom source value (e.g. run_agent_with_input).

    Phase 2 wiring adds source values: create_colony_auto,
    run_agent_with_input, run_parallel_workers. Verify the source
    column stores them verbatim.
    """
    db = ensure_progress_db(tmp_path / "c")
    tid = enqueue_task(db, "chat task", source="run_agent_with_input")
    con = sqlite3.connect(str(db))
    try:
        row = con.execute("SELECT goal, source FROM tasks WHERE id=?", (tid,)).fetchone()
        assert row == ("chat task", "run_agent_with_input")
    finally:
        con.close()


def test_claim_by_assigned_id(tmp_path: Path) -> None:
    """Worker protocol: claim a specific row by id (not the generic next-pending).

    The Phase 2 fix threads ``task_id`` into ``input_data`` when the
    queen pre-assigns a row. The worker must be able to claim THAT
    row atomically with an ``UPDATE ... WHERE id=? AND status='pending'``
    pattern, and a second claim on the same id must return 0 rows.
    """
    db = ensure_progress_db(tmp_path / "c")
    [tid] = seed_tasks(db, [{"goal": "pinned task"}])

    con = sqlite3.connect(str(db), isolation_level=None, timeout=5.0)
    try:
        cur = con.execute(
            """
            UPDATE tasks SET status='claimed', worker_id=?,
                claim_token=lower(hex(randomblob(8))),
                claimed_at=datetime('now'),
                updated_at=datetime('now')
            WHERE id=? AND status='pending'
            RETURNING id, goal
            """,
            ("w1", tid),
        )
        row = cur.fetchone()
        assert row == (tid, "pinned task"), f"expected one claim, got {row}"

        # Second attempt on the same id must affect zero rows.
        cur2 = con.execute(
            """
            UPDATE tasks SET status='claimed', worker_id=?,
                claim_token=lower(hex(randomblob(8))),
                claimed_at=datetime('now')
            WHERE id=? AND status='pending'
            RETURNING id
            """,
            ("w2", tid),
        )
        assert cur2.fetchone() is None, "second claim should affect zero rows"

        # Ensure worker_id on the row is still the first claimant.
        owner = con.execute(
            "SELECT worker_id, status FROM tasks WHERE id=?", (tid,)
        ).fetchone()
        assert owner == ("w1", "claimed")
    finally:
        con.close()


def test_claim_by_id_does_not_steal_unrelated_rows(tmp_path: Path) -> None:
    """Claim-by-id must only touch the named row, not siblings."""
    db = ensure_progress_db(tmp_path / "c")
    ids = seed_tasks(db, [{"goal": "a"}, {"goal": "b"}, {"goal": "c"}])
    target = ids[1]

    con = sqlite3.connect(str(db), isolation_level=None)
    try:
        con.execute(
            "UPDATE tasks SET status='claimed', worker_id='w1', "
            "claimed_at=datetime('now') WHERE id=? AND status='pending'",
            (target,),
        )
        statuses = dict(con.execute("SELECT goal, status FROM tasks").fetchall())
        assert statuses == {"a": "pending", "b": "claimed", "c": "pending"}
    finally:
        con.close()


def test_seed_tasks_bulk_10k(tmp_path: Path) -> None:
    """10k rows in one transaction should finish under a second on local disk."""
    db = ensure_progress_db(tmp_path / "c")
    tasks = [{"goal": f"task {i}", "seq": i} for i in range(10_000)]
    start = time.perf_counter()
    ids = seed_tasks(db, tasks)
    elapsed = time.perf_counter() - start
    assert len(ids) == 10_000
    # Generous ceiling — on CI with slow disk we've seen ~300ms.
    assert elapsed < 3.0, f"bulk seed too slow: {elapsed:.2f}s"


# ----------------------------------------------------------------------
# Atomic claim under concurrency
# ----------------------------------------------------------------------


_CLAIM_SQL = """
BEGIN IMMEDIATE;
UPDATE tasks
SET
    status = 'claimed',
    worker_id = ?,
    claim_token = lower(hex(randomblob(8))),
    claimed_at = datetime('now'),
    updated_at = datetime('now')
WHERE id = (
    SELECT id FROM tasks
    WHERE status = 'pending'
    ORDER BY priority DESC, seq, created_at
    LIMIT 1
);
"""


def _claim_one(db_path: Path, worker_id: str) -> str | None:
    """Atomic single-shot claim using RETURNING (SQLite 3.35+).

    The skill teaches agents the BEGIN IMMEDIATE + subquery UPDATE
    pattern; for an in-process test helper we use RETURNING so the
    claimed row id is returned from the same statement (no racing
    follow-up SELECT). Functionally equivalent: both approaches rely
    on the atomic subquery-UPDATE.
    """
    con = sqlite3.connect(str(db_path), isolation_level=None, timeout=10.0)
    con.execute("PRAGMA busy_timeout = 10000")
    try:
        cur = con.execute(
            """
            UPDATE tasks
            SET status = 'claimed',
                worker_id = ?,
                claim_token = lower(hex(randomblob(8))),
                claimed_at = datetime('now'),
                updated_at = datetime('now')
            WHERE id = (
                SELECT id FROM tasks
                WHERE status = 'pending'
                ORDER BY priority DESC, seq, created_at
                LIMIT 1
            )
            RETURNING id
            """,
            (worker_id,),
        )
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        con.close()


def test_claim_atomicity_under_concurrency(tmp_path: Path) -> None:
    """20 threads racing to drain 100 tasks — each task claimed exactly once."""
    db = ensure_progress_db(tmp_path / "c")
    seed_tasks(db, [{"goal": f"task {i}", "seq": i} for i in range(100)])

    claims: list[tuple[str, str]] = []
    claims_lock = threading.Lock()

    def worker(worker_id: str) -> None:
        while True:
            tid = _claim_one(db, worker_id)
            if tid is None:
                return
            with claims_lock:
                claims.append((worker_id, tid))

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    task_ids = [tid for _, tid in claims]
    assert len(task_ids) == 100, f"expected 100 claims, got {len(task_ids)}"
    assert len(set(task_ids)) == 100, "duplicate claims detected"

    con = sqlite3.connect(str(db))
    try:
        remaining = con.execute(
            "SELECT count(*) FROM tasks WHERE status='pending'"
        ).fetchone()[0]
        assert remaining == 0
        claimed = con.execute(
            "SELECT count(*) FROM tasks WHERE status='claimed'"
        ).fetchone()[0]
        assert claimed == 100
    finally:
        con.close()


# ----------------------------------------------------------------------
# Stale-claim reclaimer
# ----------------------------------------------------------------------


def test_reclaim_stale_returns_to_pending(tmp_path: Path) -> None:
    db = ensure_progress_db(tmp_path / "c")
    [tid] = seed_tasks(db, [{"goal": "stuck"}])

    # Simulate a claim made 20 minutes ago.
    con = sqlite3.connect(str(db), isolation_level=None)
    try:
        con.execute(
            "UPDATE tasks SET status='claimed', worker_id='w1', "
            "claimed_at=datetime('now', '-20 minutes') WHERE id=?",
            (tid,),
        )
    finally:
        con.close()

    reclaimed = reclaim_stale(db, stale_after_minutes=15)
    assert reclaimed == 1

    con = sqlite3.connect(str(db))
    try:
        row = con.execute(
            "SELECT status, worker_id, retry_count FROM tasks WHERE id=?", (tid,)
        ).fetchone()
        assert row == ("pending", None, 1)
    finally:
        con.close()


def test_reclaim_stale_fails_after_max_retries(tmp_path: Path) -> None:
    db = ensure_progress_db(tmp_path / "c")
    [tid] = seed_tasks(db, [{"goal": "doomed", "max_retries": 2}])

    con = sqlite3.connect(str(db), isolation_level=None)
    try:
        con.execute(
            "UPDATE tasks SET status='claimed', worker_id='w1', retry_count=2, "
            "claimed_at=datetime('now', '-20 minutes') WHERE id=?",
            (tid,),
        )
    finally:
        con.close()

    reclaim_stale(db, stale_after_minutes=15)

    con = sqlite3.connect(str(db))
    try:
        row = con.execute(
            "SELECT status, last_error FROM tasks WHERE id=?", (tid,)
        ).fetchone()
        assert row[0] == "failed"
        assert row[1] is not None and "max_retries" in row[1]
    finally:
        con.close()


def test_reclaim_stale_ignores_fresh_claims(tmp_path: Path) -> None:
    db = ensure_progress_db(tmp_path / "c")
    [tid] = seed_tasks(db, [{"goal": "working"}])

    con = sqlite3.connect(str(db), isolation_level=None)
    try:
        con.execute(
            "UPDATE tasks SET status='claimed', worker_id='w1', "
            "claimed_at=datetime('now') WHERE id=?",
            (tid,),
        )
    finally:
        con.close()

    reclaimed = reclaim_stale(db, stale_after_minutes=15)
    assert reclaimed == 0


# ----------------------------------------------------------------------
# Foreign key cascade
# ----------------------------------------------------------------------


# ----------------------------------------------------------------------
# Worker config patching for pre-existing colonies
# ----------------------------------------------------------------------


def _write_worker_cfg(path: Path, *, with_input_data: dict | None = None) -> None:
    """Write a minimal worker.json that matches the shape ensure_progress_db patches."""
    import json as _json

    cfg = {
        "name": "worker",
        "system_prompt": "You are a worker.",
        "goal": {"description": "do stuff", "success_criteria": [], "constraints": []},
        "tools": [],
    }
    if with_input_data is not None:
        cfg["input_data"] = with_input_data
    path.write_text(_json.dumps(cfg, indent=2))


def test_ensure_progress_db_patches_existing_worker_json(tmp_path: Path) -> None:
    """Pre-existing worker.json without input_data gets db_path injected."""
    import json as _json

    colony = tmp_path / "legacy_colony"
    colony.mkdir()
    _write_worker_cfg(colony / "worker.json")

    # Before: no input_data
    before = _json.loads((colony / "worker.json").read_text())
    assert "input_data" not in before

    db = ensure_progress_db(colony)

    after = _json.loads((colony / "worker.json").read_text())
    assert after["input_data"]["db_path"] == str(db)
    assert after["input_data"]["colony_id"] == "legacy_colony"
    # Other fields untouched
    assert after["system_prompt"] == "You are a worker."
    assert after["goal"]["description"] == "do stuff"


def test_ensure_progress_db_patch_is_idempotent(tmp_path: Path) -> None:
    """Second call must not rewrite the file (mtime unchanged)."""
    import time as _time

    colony = tmp_path / "idem"
    colony.mkdir()
    _write_worker_cfg(colony / "worker.json")

    ensure_progress_db(colony)
    mtime1 = (colony / "worker.json").stat().st_mtime

    _time.sleep(0.02)  # ensure any rewrite would bump mtime
    ensure_progress_db(colony)
    mtime2 = (colony / "worker.json").stat().st_mtime

    assert mtime1 == mtime2, "second ensure_progress_db must not rewrite worker.json"


def test_ensure_progress_db_preserves_existing_input_data_keys(tmp_path: Path) -> None:
    """Pre-existing input_data keys (other than db_path/colony_id) are preserved."""
    import json as _json

    colony = tmp_path / "preserved"
    colony.mkdir()
    _write_worker_cfg(
        colony / "worker.json",
        with_input_data={"custom_key": "hello", "db_path": "/stale/path.db"},
    )

    db = ensure_progress_db(colony)
    after = _json.loads((colony / "worker.json").read_text())

    assert after["input_data"]["custom_key"] == "hello"
    assert after["input_data"]["db_path"] == str(db)
    assert after["input_data"]["colony_id"] == "preserved"


def test_ensure_progress_db_skips_metadata_and_triggers(tmp_path: Path) -> None:
    """metadata.json and triggers.json are not worker configs — must not be touched."""
    import json as _json

    colony = tmp_path / "guarded"
    colony.mkdir()
    (colony / "metadata.json").write_text(_json.dumps({"colony_name": "guarded"}))
    (colony / "triggers.json").write_text(_json.dumps([{"id": "t1"}]))
    _write_worker_cfg(colony / "worker.json")

    ensure_progress_db(colony)

    meta = _json.loads((colony / "metadata.json").read_text())
    trig = _json.loads((colony / "triggers.json").read_text())
    assert "input_data" not in meta
    assert trig == [{"id": "t1"}]

    worker = _json.loads((colony / "worker.json").read_text())
    assert "input_data" in worker


def test_task_delete_cascades_to_steps_and_sop(tmp_path: Path) -> None:
    db = ensure_progress_db(tmp_path / "c")
    [tid] = seed_tasks(
        db,
        [
            {
                "goal": "cascade test",
                "steps": [{"title": "a"}, {"title": "b"}],
                "sop_items": [{"key": "k", "description": "d"}],
            }
        ],
    )

    con = sqlite3.connect(str(db), isolation_level=None)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("DELETE FROM tasks WHERE id=?", (tid,))
        assert con.execute(
            "SELECT count(*) FROM steps WHERE task_id=?", (tid,)
        ).fetchone()[0] == 0
        assert con.execute(
            "SELECT count(*) FROM sop_checklist WHERE task_id=?", (tid,)
        ).fetchone()[0] == 0
    finally:
        con.close()
