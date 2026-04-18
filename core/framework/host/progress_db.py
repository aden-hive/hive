"""Per-colony SQLite task queue + progress ledger.

Every colony gets its own ``progress.db`` under ``~/.hive/colonies/{name}/data/``.
The DB holds the colony's task queue plus per-task step and SOP checklist
rows. Workers claim tasks atomically, write progress as they execute, and
verify SOP gates before marking a task done. This gives cross-run memory
that the existing per-iteration stall detectors don't have.

The DB is driven by agents via the ``sqlite3`` CLI through
``execute_command_tool``. This module handles framework-side lifecycle:
creation, migration, queen-side bulk seeding, stale-claim reclamation.

Concurrency model:
- WAL mode on from day one so 100 concurrent workers don't serialize.
- Workers hold NO long-running connection — they ``sqlite3`` per call,
  which naturally releases locks between LLM turns.
- Atomic claim via ``BEGIN IMMEDIATE; UPDATE tasks SET status='claimed'
  WHERE id=(SELECT ... LIMIT 1)``. The subquery-form UPDATE runs inside
  the immediate transaction so racers either win the row or find zero
  affected rows.
- Stale-claim reclaimer runs on host startup: claims older than
  ``stale_after_minutes`` get returned to ``pending`` and the row's
  ``retry_count`` increments. When ``retry_count >= max_retries`` the
  row is moved to ``failed`` instead.

All writes go through ``BEGIN IMMEDIATE`` so racing readers see
consistent snapshots.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    seq             INTEGER,
    priority        INTEGER NOT NULL DEFAULT 0,
    goal            TEXT NOT NULL,
    payload         TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    worker_id       TEXT,
    claim_token     TEXT,
    claimed_at      TEXT,
    started_at      TEXT,
    completed_at    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    max_retries     INTEGER NOT NULL DEFAULT 3,
    last_error      TEXT,
    parent_task_id  TEXT REFERENCES tasks(id) ON DELETE SET NULL,
    source          TEXT
);

CREATE TABLE IF NOT EXISTS steps (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,
    title           TEXT NOT NULL,
    detail          TEXT,
    status          TEXT NOT NULL DEFAULT 'pending',
    evidence        TEXT,
    worker_id       TEXT,
    started_at      TEXT,
    completed_at    TEXT,
    UNIQUE (task_id, seq)
);

CREATE TABLE IF NOT EXISTS sop_checklist (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    key             TEXT NOT NULL,
    description     TEXT NOT NULL,
    required        INTEGER NOT NULL DEFAULT 1,
    done_at         TEXT,
    done_by         TEXT,
    note            TEXT,
    UNIQUE (task_id, key)
);

CREATE TABLE IF NOT EXISTS colony_meta (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_claimable
    ON tasks(status, priority DESC, seq, created_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_steps_task_seq
    ON steps(task_id, seq);

CREATE INDEX IF NOT EXISTS idx_sop_required_open
    ON sop_checklist(task_id, required, done_at);

CREATE INDEX IF NOT EXISTS idx_tasks_status
    ON tasks(status, updated_at);
"""

_PRAGMAS = (
    "PRAGMA journal_mode = WAL;",
    "PRAGMA synchronous = NORMAL;",
    "PRAGMA foreign_keys = ON;",
    "PRAGMA busy_timeout = 5000;",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id() -> str:
    return str(uuid.uuid4())


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with the standard pragmas applied.

    WAL mode is sticky on the file once set, so re-applying on every
    open is cheap. The other pragmas are per-connection and must be
    set each time.
    """
    con = sqlite3.connect(str(db_path), isolation_level=None, timeout=5.0)
    for pragma in _PRAGMAS:
        con.execute(pragma)
    return con


def ensure_progress_db(colony_dir: Path) -> Path:
    """Create or migrate ``{colony_dir}/data/progress.db``.

    Idempotent: safe to call on an already-initialized DB. Returns the
    absolute path to the DB file.

    Steps:
    1. Ensure ``data/`` subdir exists.
    2. Open the DB (creates the file if missing).
    3. Apply WAL + pragmas.
    4. Read ``PRAGMA user_version``; if < SCHEMA_VERSION, run the
       schema block and bump user_version.
    5. Reclaim any stale claims left from previous runs.
    6. Patch every ``*.json`` worker config in the colony dir to
       inject ``input_data.db_path`` and ``input_data.colony_id`` so
       pre-existing colonies (forked before this feature landed) get
       the tracker wiring on their next spawn.
    """
    data_dir = Path(colony_dir) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "progress.db"

    con = _connect(db_path)
    try:
        current_version = con.execute("PRAGMA user_version").fetchone()[0]
        if current_version < SCHEMA_VERSION:
            con.executescript(_SCHEMA_V1)
            con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            con.execute(
                "INSERT OR REPLACE INTO colony_meta(key, value, updated_at) "
                "VALUES (?, ?, ?)",
                ("schema_version", str(SCHEMA_VERSION), _now_iso()),
            )
            logger.info(
                "progress_db: initialized schema v%d at %s", SCHEMA_VERSION, db_path
            )

        reclaimed = _reclaim_stale_inner(con, stale_after_minutes=15)
        if reclaimed:
            logger.info(
                "progress_db: reclaimed %d stale claims at startup (%s)",
                reclaimed,
                db_path,
            )
    finally:
        con.close()

    resolved_db_path = db_path.resolve()
    _patch_worker_configs(Path(colony_dir), resolved_db_path)
    return resolved_db_path


def _patch_worker_configs(colony_dir: Path, db_path: Path) -> int:
    """Inject ``input_data.db_path`` + ``input_data.colony_id`` +
    ``input_data.colony_data_dir`` into existing ``worker.json`` files
    in a colony directory.

    Runs on every ``ensure_progress_db`` call so colonies that were
    forked before this feature landed get their worker spawn messages
    patched in place. Idempotent: if ``input_data`` already contains
    all three values, the file is not rewritten.

    Returns the number of files that were actually modified (0 on
    the common case of already-patched colonies).

    Why ``colony_data_dir``? ``db_path`` alone points agents at
    ``progress.db``; for anything else (custom SQLite stores, JSON
    ledgers, scraped artefacts) they need the *directory* so they
    stop creating state under ``~/.hive/skills/`` — which holds skill
    *definitions*, not runtime data. See
    ``_default_skills/colony-storage-paths/SKILL.md``.
    """
    colony_id = colony_dir.name
    abs_db = str(db_path)
    abs_data_dir = str(db_path.parent)
    patched = 0

    for worker_cfg in colony_dir.glob("*.json"):
        # Only patch files that look like worker configs (have the
        # worker_meta shape). ``metadata.json`` and ``triggers.json``
        # are colony-level and must not be touched.
        if worker_cfg.name in ("metadata.json", "triggers.json"):
            continue
        try:
            data = json.loads(worker_cfg.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict) or "system_prompt" not in data:
            # Not a worker config (lacks the worker_meta schema).
            continue

        input_data = data.get("input_data")
        if not isinstance(input_data, dict):
            input_data = {}

        if (
            input_data.get("db_path") == abs_db
            and input_data.get("colony_id") == colony_id
            and input_data.get("colony_data_dir") == abs_data_dir
        ):
            continue  # already patched

        input_data["db_path"] = abs_db
        input_data["colony_id"] = colony_id
        input_data["colony_data_dir"] = abs_data_dir
        data["input_data"] = input_data

        try:
            worker_cfg.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            patched += 1
        except OSError as e:
            logger.warning(
                "progress_db: failed to patch worker config %s: %s", worker_cfg, e
            )

    if patched:
        logger.info(
            "progress_db: patched %d worker config(s) in colony '%s' with "
            "db_path + colony_data_dir",
            patched,
            colony_id,
        )
    return patched


def ensure_all_colony_dbs(colonies_root: Path | None = None) -> list[Path]:
    """Idempotently ensure every existing colony has a progress.db.

    Called on framework host startup to backfill older colonies and
    run the stale-claim reclaimer on all of them in one pass.
    """
    if colonies_root is None:
        colonies_root = Path.home() / ".hive" / "colonies"
    if not colonies_root.is_dir():
        return []

    initialized: list[Path] = []
    for entry in sorted(colonies_root.iterdir()):
        if not entry.is_dir():
            continue
        try:
            initialized.append(ensure_progress_db(entry))
        except Exception as e:
            logger.warning(
                "progress_db: failed to ensure DB for colony '%s': %s", entry.name, e
            )
    return initialized


def seed_tasks(
    db_path: Path,
    tasks: list[dict[str, Any]],
    *,
    source: str = "queen_create",
) -> list[str]:
    """Bulk-insert tasks (with optional nested steps + sop_items).

    Each task dict accepts:
      - goal: str (required)
      - seq: int (optional ordering hint)
      - priority: int (default 0)
      - payload: dict | str | None (stored as JSON text)
      - max_retries: int (default 3)
      - parent_task_id: str | None
      - steps: list[{"title": str, "detail"?: str}] (optional)
      - sop_items: list[{"key": str, "description": str, "required"?: bool, "note"?: str}] (optional)

    All rows are inserted in a single BEGIN IMMEDIATE transaction so
    10k-row seeds finish in one disk flush. Returns the created task ids
    in the same order as input.
    """
    if not tasks:
        return []

    created_ids: list[str] = []
    now = _now_iso()
    con = _connect(Path(db_path))
    try:
        con.execute("BEGIN IMMEDIATE")
        for idx, task in enumerate(tasks):
            goal = task.get("goal")
            if not goal:
                raise ValueError(f"task[{idx}] missing required 'goal' field")

            task_id = task.get("id") or _new_id()
            payload = task.get("payload")
            if payload is not None and not isinstance(payload, str):
                payload = json.dumps(payload, ensure_ascii=False)

            con.execute(
                """
                INSERT INTO tasks (
                    id, seq, priority, goal, payload, status,
                    created_at, updated_at, max_retries, parent_task_id, source
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    task.get("seq"),
                    int(task.get("priority", 0)),
                    goal,
                    payload,
                    now,
                    now,
                    int(task.get("max_retries", 3)),
                    task.get("parent_task_id"),
                    source,
                ),
            )

            for step_seq, step in enumerate(task.get("steps") or [], start=1):
                if not step.get("title"):
                    raise ValueError(
                        f"task[{idx}].steps[{step_seq - 1}] missing required 'title'"
                    )
                con.execute(
                    """
                    INSERT INTO steps (id, task_id, seq, title, detail, status)
                    VALUES (?, ?, ?, ?, ?, 'pending')
                    """,
                    (
                        _new_id(),
                        task_id,
                        step.get("seq", step_seq),
                        step["title"],
                        step.get("detail"),
                    ),
                )

            for sop in task.get("sop_items") or []:
                key = sop.get("key")
                description = sop.get("description")
                if not key or not description:
                    raise ValueError(
                        f"task[{idx}].sop_items missing 'key' or 'description'"
                    )
                con.execute(
                    """
                    INSERT INTO sop_checklist
                        (id, task_id, key, description, required, note)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _new_id(),
                        task_id,
                        key,
                        description,
                        1 if sop.get("required", True) else 0,
                        sop.get("note"),
                    ),
                )

            created_ids.append(task_id)

        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()

    return created_ids


def enqueue_task(
    db_path: Path,
    goal: str,
    *,
    steps: list[dict[str, Any]] | None = None,
    sop_items: list[dict[str, Any]] | None = None,
    payload: Any = None,
    priority: int = 0,
    parent_task_id: str | None = None,
    source: str = "enqueue_tool",
) -> str:
    """Append a single task to an existing queue. Thin wrapper over seed_tasks."""
    ids = seed_tasks(
        db_path,
        [
            {
                "goal": goal,
                "steps": steps,
                "sop_items": sop_items,
                "payload": payload,
                "priority": priority,
                "parent_task_id": parent_task_id,
            }
        ],
        source=source,
    )
    return ids[0]


def _reclaim_stale_inner(
    con: sqlite3.Connection, *, stale_after_minutes: int
) -> int:
    """Reclaim stale claims. Runs inside an existing open connection.

    Two-step:
    1. Tasks past max_retries go to 'failed' with last_error populated.
    2. Remaining stale claims return to 'pending', retry_count++.
    """
    cutoff_expr = f"datetime('now', '-{int(stale_after_minutes)} minutes')"

    con.execute("BEGIN IMMEDIATE")
    try:
        con.execute(
            f"""
            UPDATE tasks
            SET status = 'failed',
                last_error = COALESCE(last_error, 'exceeded max_retries after stale claim'),
                completed_at = datetime('now'),
                updated_at = datetime('now')
            WHERE status IN ('claimed', 'in_progress')
              AND claimed_at IS NOT NULL
              AND claimed_at < {cutoff_expr}
              AND retry_count >= max_retries
            """
        )

        cur = con.execute(
            f"""
            UPDATE tasks
            SET status = 'pending',
                worker_id = NULL,
                claim_token = NULL,
                claimed_at = NULL,
                started_at = NULL,
                retry_count = retry_count + 1,
                updated_at = datetime('now')
            WHERE status IN ('claimed', 'in_progress')
              AND claimed_at IS NOT NULL
              AND claimed_at < {cutoff_expr}
              AND retry_count < max_retries
            """
        )
        reclaimed = cur.rowcount or 0
        con.execute("COMMIT")
        return reclaimed
    except Exception:
        con.execute("ROLLBACK")
        raise


def reclaim_stale(db_path: Path, stale_after_minutes: int = 15) -> int:
    """Public wrapper that opens its own connection."""
    con = _connect(Path(db_path))
    try:
        return _reclaim_stale_inner(con, stale_after_minutes=stale_after_minutes)
    finally:
        con.close()


__all__ = [
    "SCHEMA_VERSION",
    "ensure_progress_db",
    "ensure_all_colony_dbs",
    "seed_tasks",
    "enqueue_task",
    "reclaim_stale",
]
