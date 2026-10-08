"""Queen + worker tools for the per-colony tracker DB.

Four tools are wired here:

- ``tracker_sql(sql)`` — **queen-only**. Raw SQL against ``tracker.db``,
  denylist enforced (see :mod:`framework.host.tracker_db`). Returns rows
  for ``SELECT`` and ``{rowcount, last_insert_rowid}`` for DDL/DML.
  This is the queen's primary tool for designing the tracker schema and
  validating progress.

- ``tracker_register_writable(table, write_columns, key_columns)``
  — **queen-only**. Records a row in the ``_tracker_registry`` so workers
  may call :func:`tracker_upsert` against ``table``. Validates that the
  table exists, the columns exist, and that the key columns have a
  unique index that covers them. ``key_columns`` is required: workers
  must be able to upsert idempotently so re-dispatched workers don't
  create duplicate rows.

- ``tracker_upsert(table, row)`` — **shared**. The narrow worker tool.
  Looks up ``table`` in ``_tracker_registry`` and does
  ``INSERT ... ON CONFLICT(<keys>) DO UPDATE``. Refuses unregistered
  tables and ``_*`` framework tables.

- ``tracker_query(sql)`` — **shared**. SELECT-only reads against the same
  tracker DB so workers can inspect assignment context without raw SQL
  write powers.

Tools resolve their target ``tracker.db`` via :func:`current_binding` —
the single :class:`ColonyBinding` object threaded into the execution
context by ``fork_session_into_colony`` (queen) and via ``input_data``
(workers). When no binding is present the call fails with a clear
"create a colony first" error; the tools never fabricate a path.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from framework.global_db import client as gdb
from framework.global_db.count_cache import global_count_cache, note_global_used
from framework.host.colony_binding import ColonyBinding, current_binding
from framework.host.tracker_db import (
    PROTECTED_PREFIX,
    DenylistError,
    advance_crm_watermark,
    ensure_tracker_db,
    execute_sql,
    install_change_triggers,
    prune_change_log,
)
from framework.llm.provider import Tool
from framework.loader.tool_registry import ToolRegistry
from framework.tasks.tools._context import current_context

logger = logging.getLogger(__name__)


_NO_BINDING_ERROR = (
    "no colony context — this tool only works inside a colony. The "
    "queen reaches colony mode by calling suggest_colony and waiting "
    "for the user to confirm the Create Colony popup; workers receive "
    "the binding via input_data automatically."
)


def _binding_from_legacy_context() -> ColonyBinding | None:
    """Build a binding from pre-ColonyBinding execution context fields.

    Older worker sessions and some tests still pass loose ``tracker_db_path``
    / ``colony_id`` fields. Prefer explicit ``tracker_db_path`` when present;
    otherwise only accept ``colony_id`` if its colony directory already
    exists, so a session id cannot silently create a shadow colony.
    """
    ctx = current_context()

    raw_path = ctx.get("tracker_db_path")
    if isinstance(raw_path, str) and raw_path:
        db_path = Path(raw_path)
        if db_path.name == "tracker.db" and db_path.parent.name in {"data", "tracker"}:
            colony_dir = db_path.parent.parent
        else:
            colony_dir = db_path.parent

        tracker_db = ensure_tracker_db(colony_dir)
        name = str(ctx.get("colony_id") or colony_dir.name)
        return ColonyBinding(name=name, dir=colony_dir, tracker_db=tracker_db)

    colony_id = ctx.get("colony_id")
    if isinstance(colony_id, str) and colony_id:
        from framework.config import COLONIES_DIR

        colony_dir = COLONIES_DIR / colony_id
        if not colony_dir.exists():
            return None
        tracker_db = ensure_tracker_db(colony_dir)
        return ColonyBinding(name=colony_id, dir=colony_dir, tracker_db=tracker_db)

    return None


def _require_binding() -> ColonyBinding | dict[str, Any]:
    """Return the binding for the current call, or a failure-shaped dict.

    Callers check ``isinstance(result, ColonyBinding)``; on the dict
    branch the tool returns the dict verbatim as its failure payload.
    """
    binding = current_binding()
    if binding is None:
        binding = _binding_from_legacy_context()
    if binding is None:
        return {"success": False, "error": _NO_BINDING_ERROR}
    return binding


# ---------------------------------------------------------------------------
# scope="global" → the shared cloud team global DB (hive-backend /v1/global-db/*)
#
# scope="colony" (default) keeps the existing per-colony SQLite behavior.
# scope="global" routes to the team's cloud Postgres global DB via the
# global-db client; it needs a signed-in cloud session, not a colony binding.
# ---------------------------------------------------------------------------

_SCOPE_PARAM = {
    "type": "string",
    "enum": ["colony", "global"],
    "description": (
        "Which tracker to target. 'colony' (default) is THIS colony's private "
        "tracker.db (local — your work queue). 'global' targets the team's shared "
        "cloud database (requires a signed-in cloud session; other colonies read/"
        "write it too, so scope queries to your own rows and expand the schema only "
        "additively). For go-to-market people/accounts, use the `hive-crm` CLI (the "
        "team CRM) — not raw global tracker writes."
    ),
}


def _scope_of(inputs: dict) -> str:
    return (inputs.get("scope") or "colony").strip().lower()


def _ambient_colony_name() -> str | None:
    binding = current_binding()
    return binding.name if binding is not None else None


def _shape_cloud_sql(res: dict[str, Any]) -> dict[str, Any]:
    """Map the backend's {columns, rows(objects), rowCount, truncated} onto the
    colony tracker shape ({kind:'rows'|'exec', columns, rows(positional), …}) so
    the agent sees one consistent contract across scopes."""
    columns = res.get("columns") or []
    raw_rows = res.get("rows") or []
    if columns:
        rows = [[r.get(c) for c in columns] for r in raw_rows]
        return {
            "kind": "rows",
            "columns": columns,
            "rows": rows,
            "rowcount": res.get("rowCount", len(rows)),
            "truncated": res.get("truncated", False),
        }
    return {"kind": "exec", "rowcount": res.get("rowCount", 0)}


def _globally_mutated_tables(sql_text: str) -> set[str]:
    """Best-effort lowercase table names mutated by a scope='global' script.

    Reuses the tracker denylist's statement parser (verb resolution handles
    WITH-prefixed DML; comments are stripped). Used only to *observe*
    promotions — a miss means one skipped watermark advance, never a
    wrong nag.
    """
    from framework.host.tracker_db import (
        _MUTATING_KEYWORDS,
        _effective_statement,
        _referenced_tables_for_mutation,
        _split_statements,
    )

    out: set[str] = set()
    try:
        for stmt in _split_statements(sql_text):
            verb, body = _effective_statement(stmt)
            if verb in _MUTATING_KEYWORDS:
                out.update(t.lower() for t in _referenced_tables_for_mutation(body))
    except Exception:
        logger.debug("crm watermark: mutation parse failed", exc_info=True)
    return out


def _observe_global_promotion(mutated_tables: set[str]) -> None:
    """Advance the local promote watermark when a global CRM write to
    ``leads`` is observed. The write chokepoint IS the promotion signal —
    no global query needed (see tracker_db's CRM promote-link section).

    Resolves the binding the same way the tools do (ambient binding, then
    legacy context) so the observation works wherever the write worked.
    """
    if "leads" not in mutated_tables:
        return
    binding = current_binding()
    if binding is None:
        binding = _binding_from_legacy_context()
    if binding is None:
        return
    try:
        advance_crm_watermark(binding.tracker_db)
    except Exception:
        logger.debug("crm watermark: advance failed", exc_info=True)


async def _global_sql(inputs: dict, *, read_only: bool) -> dict[str, Any]:
    note_global_used()
    sql_text = inputs.get("sql")
    if not isinstance(sql_text, str) or not sql_text.strip():
        return {"success": False, "error": "'sql' is required."}
    row_cap = int(inputs.get("row_cap") or 1000)
    caller = gdb.query if read_only else gdb.sql
    try:
        res = await caller(sql_text, row_cap=row_cap)
    except gdb.NotSignedInError as e:
        return {"success": False, "error": str(e)}
    except gdb.GlobalDbError as e:
        return {"success": False, "error": f"global DB error: {e}"}
    # A write may have changed row counts — invalidate the reminder cache.
    if not read_only:
        global_count_cache.mark_dirty()
        _observe_global_promotion(_globally_mutated_tables(sql_text))
    return {"success": True, **_shape_cloud_sql(res)}


async def _global_upsert(inputs: dict) -> dict[str, Any]:
    note_global_used()
    table = (inputs.get("table") or "").strip()
    if not table:
        return {"success": False, "error": "table is required"}
    row = inputs.get("row")
    if not isinstance(row, dict) or not row:
        return {"success": False, "error": "row must be a non-empty object of column→value"}
    try:
        res = await gdb.upsert(table, row, source_colony=_ambient_colony_name())
    except gdb.NotSignedInError as e:
        return {"success": False, "error": str(e)}
    except gdb.GlobalDbError as e:
        return {"success": False, "error": f"global DB error: {e}"}
    global_count_cache.mark_dirty()
    _observe_global_promotion({table.lower()})
    return {"success": True, "table": table, "rowcount": res.get("inserted", 1)}


def _global_register_info() -> dict[str, Any]:
    """scope='global' has no registry: the team schema uses free DDL, so workers
    may upsert into any existing table directly."""
    note_global_used()
    return {
        "success": True,
        "message": (
            "The global DB uses free DDL within your team's schema — no "
            "registration is needed. Workers may tracker_upsert(scope='global') "
            "into any existing table; use tracker_sql(scope='global') to "
            "CREATE/ALTER tables."
        ),
    }


# ---------------------------------------------------------------------------
# tracker_sql (queen-only)
# ---------------------------------------------------------------------------


_TRACKER_SQL_DESC = (
    "Run raw SQL against this colony's tracker.db. The tracker is your "
    "queen-owned domain model — design the table(s) that describe progress "
    "toward the goal, then validate worker output by querying the table.\n\n"
    "Typical workflow after the colony is created:\n"
    "  1. CREATE TABLE <name> (...)  -- design columns that describe one "
    "unit of progress (one row = one company, one paper, one row, etc.).\n"
    "  2. INSERT INTO <name> (key_col, ...) VALUES (...)  -- seed primary "
    "keys you already know so workers fan out across disjoint rows.\n"
    "  3. tracker_register_writable(...)  -- whitelist which columns "
    "workers may write to; without this they cannot upsert.\n"
    "  4. run_worker(...)  -- delegate row-fill work.\n"
    "  5. SELECT ... WHERE <col> IS NULL  -- find gaps; re-dispatch if needed.\n\n"
    "Returns:\n"
    "  - SELECT: {kind: 'rows', columns: [...], rows: [[...], ...], "
    "rowcount, truncated}. Rows past row_cap are dropped (truncated=true); "
    "paginate with LIMIT/OFFSET.\n"
    "  - DDL/DML: {kind: 'exec', rowcount, last_insert_rowid}.\n"
    "  - Multi-statement script (statements separated by ';'): "
    "{kind: 'script', results: [<per-stmt result>, ...]}.\n\n"
    "Forbidden: ATTACH, DETACH, PRAGMA, VACUUM, REINDEX, load_extension(). "
    "Tables starting with '_' are framework-owned (DDL/DML rejected; "
    "SELECT is fine). Cap of 20 statements per call."
)


def _tracker_sql_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": (
                    "Raw SQL. May be a single statement or a script of "
                    "statements separated by ';'. CTEs, transactions "
                    "(BEGIN/COMMIT), and views are allowed."
                ),
            },
            "row_cap": {
                "type": "integer",
                "description": "Max rows returned per SELECT (default 1000).",
                "minimum": 1,
                "maximum": 10000,
            },
            "scope": _SCOPE_PARAM,
        },
        "required": ["sql"],
    }


def _make_tracker_sql_executor():
    async def execute(inputs: dict) -> dict[str, Any]:
        if _scope_of(inputs) == "global":
            return await _global_sql(inputs, read_only=False)
        binding_or_error = _require_binding()
        if not isinstance(binding_or_error, ColonyBinding):
            return binding_or_error
        binding = binding_or_error
        sql = inputs.get("sql")
        if not isinstance(sql, str) or not sql.strip():
            return {"success": False, "error": "tracker_sql: 'sql' is required."}
        # Make sure tracker.db exists. The fork flow already calls
        # ensure_tracker_db, so this is just defensive (e.g. when the
        # queen runs tracker_sql before any worker has spawned).
        try:
            ensure_tracker_db(binding.dir)
        except Exception as e:
            logger.exception("tracker_sql: ensure_tracker_db failed")
            return {"success": False, "error": f"tracker_sql: {e}"}

        row_cap = int(inputs.get("row_cap") or 1000)
        try:
            result = execute_sql(binding.tracker_db, sql, row_cap=row_cap)
        except DenylistError as e:
            return {"success": False, "error": f"tracker_sql denied: {e}"}
        except sqlite3.Error as e:
            # Surface SQLite errors verbatim so the queen can debug her schema.
            return {"success": False, "error": f"tracker_sql sqlite error: {e}"}
        return {"success": True, **result}

    return execute


# ---------------------------------------------------------------------------
# tracker_register_writable (queen-only)
# ---------------------------------------------------------------------------


_TRACKER_REGISTER_DESC = (
    "Whitelist a tracker table for worker writes. Workers cannot call "
    "tracker_upsert against an unregistered table — without registration "
    "the table is invisible to them. Call this after CREATE TABLE.\n\n"
    "Args:\n"
    "  table         — the table name in tracker.db (must already exist).\n"
    "  write_columns — list of columns workers may set on each row.\n"
    "                  Columns NOT in this list (e.g. an internal "
    "                  'reviewed_at') stay queen-only.\n"
    "  key_columns   — REQUIRED. List of columns that uniquely identify "
    "                  a row (used for ON CONFLICT). Without keys, "
    "                  re-dispatched workers create duplicate rows "
    "                  instead of updating in place. Add a PRIMARY KEY "
    "                  or UNIQUE INDEX on the table before registering.\n\n"
    "Validation: the table must exist in tracker.db, every named column "
    "must exist, key_columns must be non-empty, and the key_columns "
    "must be covered by a UNIQUE index (a PRIMARY KEY counts). "
    "Re-registering a table is fine — the new spec replaces the old one."
)


def _tracker_register_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "table": {
                "type": "string",
                "description": "Tracker table name (must already exist).",
            },
            "write_columns": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": ("Columns workers may write. Other columns stay queen-only."),
            },
            "key_columns": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": (
                    "Required. Columns that uniquely identify a row (for "
                    "ON CONFLICT). Must be covered by a PRIMARY KEY or "
                    "UNIQUE index so re-dispatched workers update in "
                    "place instead of creating duplicate rows."
                ),
            },
            "scope": _SCOPE_PARAM,
        },
        "required": ["table", "write_columns", "key_columns"],
    }


def _table_columns(con: sqlite3.Connection, table: str) -> list[str]:
    """Return ordered column names for ``table``, or [] if missing."""
    # Direct PRAGMA call from framework code — denylist applies only to
    # user-supplied SQL routed through validate_sql.
    rows = con.execute(f"PRAGMA table_info({_quote_ident(table)})").fetchall()
    return [r[1] for r in rows]


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def _quote_ident(name: str) -> str:
    """Quote a SQLite identifier safely (double the embedded double-quotes)."""
    return '"' + name.replace('"', '""') + '"'


def _key_columns_uniquely_indexed(con: sqlite3.Connection, table: str, keys: list[str]) -> bool:
    """True if some unique index on ``table`` covers exactly ``keys``.

    Order matters in SQLite indices but not for our purposes (ON CONFLICT
    doesn't care about declaration order). We compare as sets.
    """
    keys_set = set(keys)
    idx_rows = con.execute(f"PRAGMA index_list({_quote_ident(table)})").fetchall()
    for idx in idx_rows:
        # PRAGMA index_list columns: seq, name, unique, origin, partial
        idx_name, is_unique = idx[1], bool(idx[2])
        if not is_unique:
            continue
        cols = [r[2] for r in con.execute(f"PRAGMA index_info({_quote_ident(idx_name)})").fetchall()]
        if set(cols) == keys_set:
            return True
    return False


def _make_tracker_register_executor():
    async def execute(inputs: dict) -> dict[str, Any]:
        if _scope_of(inputs) == "global":
            return _global_register_info()

        from framework.host.tracker_db import _connect, _now_iso

        binding_or_error = _require_binding()
        if not isinstance(binding_or_error, ColonyBinding):
            return binding_or_error
        binding = binding_or_error

        table = (inputs.get("table") or "").strip()
        if not table:
            return {"success": False, "error": "table is required"}
        if table.startswith(PROTECTED_PREFIX):
            return {
                "success": False,
                "error": (f"table '{table}' is in the protected '{PROTECTED_PREFIX}*' namespace and cannot be registered for worker writes."),
            }

        write_columns = inputs.get("write_columns") or []
        if not isinstance(write_columns, list) or not all(isinstance(c, str) and c for c in write_columns):
            return {
                "success": False,
                "error": "write_columns must be a non-empty list of strings",
            }

        key_columns = inputs.get("key_columns") or []
        if not isinstance(key_columns, list) or not all(isinstance(c, str) and c for c in key_columns):
            return {
                "success": False,
                "error": "key_columns must be a list of strings",
            }
        if not key_columns:
            # Append-mode (no keys) lets re-dispatched workers create
            # duplicate rows. Force the queen to pick a key so upserts
            # are idempotent.
            return {
                "success": False,
                "error": (
                    "key_columns is required and must be non-empty. "
                    "Without keys, workers can't upsert idempotently — "
                    "re-dispatched workers would create duplicate rows. "
                    "Add a PRIMARY KEY or UNIQUE INDEX on the table and "
                    "pass those column(s) as key_columns."
                ),
            }

        mode = "upsert"

        # Make sure the DB exists; the fork flow does this, but a fresh
        # tracker_register_writable call before any other tracker activity
        # should still succeed.
        ensure_tracker_db(binding.dir)

        con = _connect(binding.tracker_db)
        try:
            if not _table_exists(con, table):
                return {
                    "success": False,
                    "error": (f"table '{table}' does not exist in tracker.db. CREATE the table via tracker_sql first."),
                }

            actual_cols = _table_columns(con, table)
            actual_set = set(actual_cols)
            missing_write = [c for c in write_columns if c not in actual_set]
            if missing_write:
                return {
                    "success": False,
                    "error": (f"write_columns not found on '{table}': {missing_write}. Existing: {actual_cols}"),
                }
            missing_key = [c for c in key_columns if c not in actual_set]
            if missing_key:
                return {
                    "success": False,
                    "error": (f"key_columns not found on '{table}': {missing_key}"),
                }

            if mode == "upsert" and not _key_columns_uniquely_indexed(con, table, key_columns):
                return {
                    "success": False,
                    "error": (
                        f"key_columns {key_columns} are not covered by a "
                        f"UNIQUE index on '{table}'. Add PRIMARY KEY or "
                        "CREATE UNIQUE INDEX before registering for upsert."
                    ),
                }

            con.execute(
                """
                INSERT INTO _tracker_registry
                    (table_name, write_columns, key_columns, mode, registered_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(table_name) DO UPDATE SET
                    write_columns = excluded.write_columns,
                    key_columns   = excluded.key_columns,
                    mode          = excluded.mode,
                    registered_at = excluded.registered_at
                """,
                (
                    table,
                    json.dumps(list(write_columns)),
                    json.dumps(list(key_columns)),
                    mode,
                    _now_iso(),
                ),
            )
            # Install the row-level change-log triggers alongside the
            # registration — from here on, every write to this table
            # (worker upsert, queen SQL, UI edit) is logged with its pk
            # so the UI can show which rows changed. Re-registration
            # rebuilds them with the new key_columns.
            install_change_triggers(con, table, [str(k) for k in key_columns])
        finally:
            con.close()

        return {
            "success": True,
            "table": table,
            "write_columns": list(write_columns),
            "key_columns": list(key_columns),
            "mode": mode,
            "message": (f"Registered '{table}' for worker writes (mode={mode}, key_columns={key_columns})."),
        }

    return execute


# ---------------------------------------------------------------------------
# tracker_upsert (worker-facing)
# ---------------------------------------------------------------------------


_TRACKER_UPSERT_DESC = (
    "Write a row to a tracker table the queen has registered for worker "
    "writes. This is your channel for reporting findings — prefer it over "
    "embedding structured data in your final-message text, because the "
    "queen reads tracker rows directly and can validate them.\n\n"
    "Args:\n"
    "  table — the registered tracker table.\n"
    "  row   — dict of column→value. Must include all key_columns the "
    "          queen registered. Columns not in the registered "
    "          write_columns (or key_columns) are rejected.\n\n"
    "Behavior: INSERT ... ON CONFLICT(<keys>) DO UPDATE — call again "
    "with the same key to update the row in place.\n\n"
    "Refuses unregistered tables and any '_*' framework table."
)


def _tracker_upsert_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "table": {"type": "string"},
            "row": {
                "type": "object",
                "description": ("Column→value pairs. Values may be string, number, boolean, or null. Lists/objects are JSON-encoded before write."),
            },
            "scope": _SCOPE_PARAM,
        },
        "required": ["table", "row"],
    }


# ---------------------------------------------------------------------------
# tracker_query (shared — SELECT-only)
# ---------------------------------------------------------------------------


_TRACKER_QUERY_DESC = (
    "Read rows from the colony's tracker.db. SELECT-only — DDL, INSERT, "
    "UPDATE, and DELETE are rejected (use tracker_upsert for writes).\n\n"
    'Workers: use this to read your assignment context (e.g. "which '
    'rows still need work", "what columns are expected") instead of '
    "asking the queen. The queen has already designed the table; you "
    "can introspect via SELECT against ``sqlite_master`` or the table "
    "directly.\n\n"
    "Queen: also fine to use for read-only checks; tracker_sql covers "
    "the same ground with broader powers.\n\n"
    "Returns ``{kind: 'rows', columns: [...], rows: [[...], ...], "
    "rowcount, truncated}``. Rows past row_cap are dropped (truncated="
    "true); paginate with LIMIT/OFFSET.\n\n"
    "Allowed: SELECT, WITH, EXPLAIN. Forbidden: ATTACH, DETACH, PRAGMA, "
    "VACUUM, REINDEX, load_extension(), and ALL writes/DDL."
)


def _tracker_query_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": ("SELECT (or WITH … SELECT) statement. Single statement; scripts not allowed."),
            },
            "row_cap": {
                "type": "integer",
                "description": "Max rows returned (default 1000).",
                "minimum": 1,
                "maximum": 10000,
            },
            "scope": _SCOPE_PARAM,
        },
        "required": ["sql"],
    }


# Statement verbs that count as "read" — anything else is rejected.
# WITH is deliberately absent: a WITH-prefixed statement resolves to its
# main verb (SQLite allows ``WITH ... INSERT/UPDATE/DELETE``), so a pure
# CTE read arrives here as SELECT while WITH-wrapped DML keeps its
# write verb and is rejected.
_READ_KEYWORDS = frozenset({"SELECT", "EXPLAIN"})


def _make_tracker_query_executor():
    async def execute(inputs: dict) -> dict[str, Any]:
        if _scope_of(inputs) == "global":
            return await _global_sql(inputs, read_only=True)

        from framework.host.tracker_db import (
            _effective_statement,
            _split_statements,
        )

        binding_or_error = _require_binding()
        if not isinstance(binding_or_error, ColonyBinding):
            return binding_or_error
        binding = binding_or_error
        sql = inputs.get("sql")
        if not isinstance(sql, str) or not sql.strip():
            return {"success": False, "error": "tracker_query: 'sql' is required."}

        # Reject anything that isn't a pure read. Multi-statement scripts
        # are also rejected — the worker should issue one SELECT per call
        # so write-attempts disguised in a script can't slip through.
        statements = _split_statements(sql)
        if not statements:
            return {"success": False, "error": "tracker_query: no statements"}
        if len(statements) > 1:
            return {
                "success": False,
                "error": (f"tracker_query accepts ONE statement per call (got {len(statements)}). Use tracker_sql for scripts."),
            }
        verb, _body = _effective_statement(statements[0])
        if verb not in _READ_KEYWORDS:
            return {
                "success": False,
                "error": (f"tracker_query is SELECT-only; rejected statement verb '{verb}'. For writes, use tracker_upsert."),
            }

        # The denylist (ATTACH/PRAGMA/load_extension/etc.) still applies
        # via execute_sql → validate_sql. The leading-keyword check above
        # is stricter than validate_sql (which permits write DML); the
        # denylist sits underneath as belt-and-suspenders.
        row_cap = int(inputs.get("row_cap") or 1000)
        try:
            result = execute_sql(binding.tracker_db, sql, row_cap=row_cap)
        except DenylistError as e:
            return {"success": False, "error": f"tracker_query denied: {e}"}
        except sqlite3.Error as e:
            return {"success": False, "error": f"tracker_query sqlite error: {e}"}
        return {"success": True, **result}

    return execute


# ---------------------------------------------------------------------------
# tracker_upsert (worker-facing)
# ---------------------------------------------------------------------------


def _make_tracker_upsert_executor():
    async def execute(inputs: dict) -> dict[str, Any]:
        if _scope_of(inputs) == "global":
            return await _global_upsert(inputs)

        from framework.host.tracker_db import _connect

        binding_or_error = _require_binding()
        if not isinstance(binding_or_error, ColonyBinding):
            return binding_or_error
        binding = binding_or_error

        table = (inputs.get("table") or "").strip()
        if not table:
            return {"success": False, "error": "table is required"}
        if table.startswith(PROTECTED_PREFIX):
            return {
                "success": False,
                "error": (f"refusing to write to framework-owned table '{table}' ({PROTECTED_PREFIX}* is reserved)."),
            }

        row = inputs.get("row")
        if not isinstance(row, dict) or not row:
            return {
                "success": False,
                "error": "row must be a non-empty object of column→value",
            }

        con = _connect(binding.tracker_db)
        try:
            reg = con.execute(
                "SELECT write_columns, key_columns, mode FROM _tracker_registry WHERE table_name = ?",
                (table,),
            ).fetchone()
            if reg is None:
                return {
                    "success": False,
                    "error": (f"table '{table}' is not registered for worker writes. The queen must call tracker_register_writable first."),
                }
            write_columns_raw, key_columns_raw, mode = reg
            try:
                write_columns = list(json.loads(write_columns_raw))
                key_columns = list(json.loads(key_columns_raw))
            except (json.JSONDecodeError, TypeError):
                return {
                    "success": False,
                    "error": "registry row is corrupt; re-register the table",
                }

            allowed_for_writes = set(write_columns) | set(key_columns)
            unknown = [c for c in row.keys() if c not in allowed_for_writes]
            if unknown:
                return {
                    "success": False,
                    "error": (f"columns not in write/key list: {unknown}. Allowed: {sorted(allowed_for_writes)}"),
                }

            if mode == "upsert":
                missing_keys = [k for k in key_columns if k not in row]
                if missing_keys:
                    return {
                        "success": False,
                        "error": (f"row is missing key_columns {missing_keys} required for upsert"),
                    }

            # Encode complex values as JSON text so the row is always
            # column-shaped from SQLite's view.
            cols = list(row.keys())
            values = []
            for c in cols:
                v = row[c]
                if isinstance(v, list | dict):
                    values.append(json.dumps(v, ensure_ascii=False))
                elif isinstance(v, bool):
                    values.append(1 if v else 0)
                else:
                    values.append(v)

            quoted_cols = ", ".join(_quote_ident(c) for c in cols)
            placeholders = ", ".join(["?"] * len(cols))
            base_sql = f"INSERT INTO {_quote_ident(table)} ({quoted_cols}) VALUES ({placeholders})"

            if mode == "upsert":
                update_cols = [c for c in cols if c not in key_columns]
                if update_cols:
                    set_clause = ", ".join(f"{_quote_ident(c)} = excluded.{_quote_ident(c)}" for c in update_cols)
                    conflict = ", ".join(_quote_ident(k) for k in key_columns)
                    sql = f"{base_sql} ON CONFLICT ({conflict}) DO UPDATE SET {set_clause}"
                else:
                    # Row carried only key columns -- nothing to update.
                    conflict = ", ".join(_quote_ident(k) for k in key_columns)
                    sql = f"{base_sql} ON CONFLICT ({conflict}) DO NOTHING"
            else:
                sql = base_sql

            try:
                cur = con.execute(sql, values)
            except sqlite3.Error as e:
                return {
                    "success": False,
                    "error": f"tracker_upsert sqlite error: {e}",
                }

            # Opportunistic change-log cap: worker fill-in runs can write
            # for long stretches without any queen call touching the DB,
            # so the queen-side prune (ensure_tracker_db) alone is not
            # enough to bound the log.
            prune_change_log(con)

            return {
                "success": True,
                "table": table,
                "mode": mode,
                "rowcount": cur.rowcount,
                "last_insert_rowid": cur.lastrowid,
            }
        finally:
            con.close()

    return execute


# ---------------------------------------------------------------------------
# Public registration
# ---------------------------------------------------------------------------


# Tools that should NEVER appear in worker.json — they're the queen's
# levers (full SQL, registry writes, CRM linking). The fork flow filters
# worker tool inheritance against this set.
QUEEN_ONLY_TRACKER_TOOLS: frozenset[str] = frozenset({"tracker_sql", "tracker_register_writable"})


def build_tracker_tools() -> list[tuple[Tool, Any]]:
    """Build (Tool, executor) pairs for the tracker tools."""
    return [
        (
            Tool(
                name="tracker_sql",
                description=_TRACKER_SQL_DESC,
                parameters=_tracker_sql_schema(),
                concurrency_safe=False,
            ),
            _make_tracker_sql_executor(),
        ),
        (
            Tool(
                name="tracker_register_writable",
                description=_TRACKER_REGISTER_DESC,
                parameters=_tracker_register_schema(),
                concurrency_safe=False,
            ),
            _make_tracker_register_executor(),
        ),
        (
            Tool(
                name="tracker_upsert",
                description=_TRACKER_UPSERT_DESC,
                parameters=_tracker_upsert_schema(),
                concurrency_safe=False,
            ),
            _make_tracker_upsert_executor(),
        ),
        (
            Tool(
                name="tracker_query",
                description=_TRACKER_QUERY_DESC,
                parameters=_tracker_query_schema(),
                concurrency_safe=True,
            ),
            _make_tracker_query_executor(),
        ),
        # crm_link retired: it linked a local tracker table to the legacy global
        # leads/interactions promote loop, which the GTM lifecycle no longer uses
        # (people now go to the team CRM via the `hive-crm` CLI). Left out of the
        # agent surface; the executor/schema/desc below are dead code.
    ]


def _wrap_async_executor(async_executor):
    """Mirror the adapter used by other tool-registration helpers."""

    def executor(inputs: dict) -> Any:
        return async_executor(inputs)

    return executor


def _reject_global_scope(async_executor):
    """Wrap a shared tracker executor so workers can't reach the global DB.

    ``scope='global'`` is queen-only: the queen owns the shared cross-colony
    team DB (claim/dedup, promotion); workers write only their colony tracker
    and report results up. This is defense-in-depth alongside the worker
    prompt, which doesn't mention the global DB at all.
    """

    async def guarded(inputs: dict) -> Any:
        if (inputs.get("scope") or "colony").strip().lower() == "global":
            return {
                "success": False,
                "error": (
                    "scope='global' is queen-only — workers write only the "
                    "colony tracker. Record your result here (scope='colony') "
                    "and report it to the queen; she owns the shared global DB."
                ),
            }
        return await async_executor(inputs)

    return guarded


def register_tracker_tools(registry: ToolRegistry, *, role: str = "queen") -> None:
    """Register the tracker tools on ``registry``.

    Idempotent: re-registering replaces the previous executor.

    Args:
        registry: The ToolRegistry instance to register on.
        role: Which subset to register.
            - ``"queen"`` (default): all three tools.
            - ``"worker"``: only ``tracker_upsert``. Even though the
              worker.json ``tools`` list filters by name, registering
              the queen-only pair on a worker's registry would still
              let any non-LLM caller invoke them through the executor.
              Restricting registration is defense-in-depth.

    Raises:
        ValueError: ``role`` is not ``"queen"`` or ``"worker"``.
    """
    if role not in ("queen", "worker"):
        raise ValueError(f"role must be 'queen' or 'worker', got {role!r}")

    pairs = build_tracker_tools()
    registered: list[str] = []
    for tool, async_executor in pairs:
        if role == "worker":
            if tool.name in QUEEN_ONLY_TRACKER_TOOLS:
                continue
            # Workers get colony-scope only; scope='global' is queen-owned.
            async_executor = _reject_global_scope(async_executor)
        registry.register(tool.name, tool, _wrap_async_executor(async_executor))
        registered.append(tool.name)
    logger.debug(
        "Registered tracker tools on %s (role=%s): %s",
        registry,
        role,
        registered,
    )


__all__ = [
    "QUEEN_ONLY_TRACKER_TOOLS",
    "build_tracker_tools",
    "register_tracker_tools",
]
