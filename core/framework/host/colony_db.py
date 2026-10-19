"""Per-colony bookkeeping SQLite store — ``colonies/<id>/colony.db``.

Deliberately separate from the domain tracker (``tracker/tracker.db``). The
tracker holds work-state the queen models and workers write; ``colony.db`` holds
framework bookkeeping — currently the playbook run-log. Keeping them apart
preserves the tracker as pure domain state (design v0.4 §3.1, §11) and keeps the
run-log out of the agent-writable SQL surface.

This is observability only — never the resume authority. Losing it cannot
corrupt a run (resume keys on domain rows).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from framework.config import colony_dir

logger = logging.getLogger(__name__)

_PLAYBOOK_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS playbook_runs (
    run_id        TEXT PRIMARY KEY,
    name          TEXT,
    status        TEXT NOT NULL,           -- 'done' | 'error'
    dispatched    INTEGER NOT NULL DEFAULT 0,
    dead_lettered INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    result_json   TEXT,                    -- the playbook run() return value
    logs_json     TEXT,                    -- the log() narration lines
    created_at    TEXT NOT NULL
);
"""


def colony_db_path(colony_id: str) -> Path:
    """Path to a colony's bookkeeping DB (sibling of metadata.json, NOT the
    tracker)."""
    return colony_dir(colony_id) / "colony.db"


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA journal_mode = WAL")
    con.execute(_PLAYBOOK_RUNS_SCHEMA)
    return con


def record_playbook_run(
    db_path: Path,
    *,
    run_id: str,
    name: str | None,
    status: str,
    dispatched: int = 0,
    dead_lettered: int = 0,
    error: str | None = None,
    result: Any = None,
    logs: list[str] | None = None,
) -> None:
    """Upsert one playbook-run row. Idempotent on ``run_id`` (a re-run reuses
    its id only if the caller reuses it; the tool mints a fresh id per run)."""
    con = _connect(Path(db_path))
    try:
        con.execute(
            """
            INSERT OR REPLACE INTO playbook_runs
                (run_id, name, status, dispatched, dead_lettered, error,
                 result_json, logs_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                name,
                status,
                int(dispatched),
                int(dead_lettered),
                error,
                json.dumps(result, default=str) if result is not None else None,
                json.dumps(logs or []),
                datetime.now(UTC).isoformat(),
            ),
        )
        con.commit()
    finally:
        con.close()


def list_playbook_runs(db_path: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    """Most-recent-first run records, for review / a future viewer tool."""
    p = Path(db_path)
    if not p.exists():
        return []
    con = _connect(p)
    try:
        cur = con.execute(
            "SELECT run_id, name, status, dispatched, dead_lettered, error, "
            "result_json, logs_json, created_at FROM playbook_runs "
            "ORDER BY created_at DESC LIMIT ?",
            (int(limit),),
        )
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
    finally:
        con.close()


__all__ = ["colony_db_path", "list_playbook_runs", "record_playbook_run"]
