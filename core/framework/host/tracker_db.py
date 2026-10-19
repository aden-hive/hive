"""Per-colony tracker DB: queen-owned domain model with raw-SQL freedom.

Every colony gets its own ``tracker.db`` under
``~/.hive/colonies/{name}/data/``. The queen designs the schema with
full SQL via ``execute_sql`` (denylist enforced). Workers fill rows
through a narrower ``tracker_upsert`` tool, gated by the
``_tracker_registry`` table.

Concurrency:
- WAL mode on day one.
- Workers/queen open a fresh connection per call (``sqlite3`` CLI for
  agents, ``_connect`` for framework code).
- ``BEGIN IMMEDIATE`` for any multi-statement script that mutates state
  (the queen wraps her own transactions when she wants atomicity).

The denylist is intentionally small. The queen has been explicitly given
"raw SQL DDL" freedom; we only block what would breach the security
perimeter or break the framework:
  - ATTACH / DETACH (escape from tracker.db)
  - PRAGMA (operational; introspection works via sqlite_master)
  - VACUUM / REINDEX (operational, not domain)
  - load_extension(...) (security)
  - DDL/DML on ``_*`` tables (framework-owned namespace)
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 3

# Bootstrap schema. Only framework-owned tables; everything else is the
# queen's. ``_tracker_registry`` is what gates ``tracker_upsert`` for
# workers — without a row here, a table is invisible to workers.
# ``_tracker_changes`` is the row-level change log: triggers installed
# at registration time append one entry per written row, so the UI can
# show *which* rows changed, not just that counts moved.
_BOOTSTRAP_SCHEMA = """
CREATE TABLE IF NOT EXISTS _tracker_registry (
    table_name      TEXT PRIMARY KEY,
    write_columns   TEXT NOT NULL,    -- JSON array of column names
    key_columns     TEXT NOT NULL,    -- JSON array; empty = append mode
    mode            TEXT NOT NULL CHECK (mode IN ('upsert', 'append')),
    registered_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS _tracker_meta (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS _tracker_changes (
    id              INTEGER PRIMARY KEY,  -- monotonic cursor for "since" reads
    table_name      TEXT NOT NULL,
    pk              TEXT NOT NULL,        -- JSON object of key column -> value
    op              TEXT NOT NULL CHECK (op IN ('insert', 'update')),
    changed_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS _tracker_changes_table_id
    ON _tracker_changes (table_name, id);
"""

# Keep at most this many change-log entries; older ones are pruned
# opportunistically on write paths. Bounds the size cost the snapshot
# byte-copy read path pays for the log.
CHANGE_LOG_MAX = 10_000

_PRAGMAS = (
    "PRAGMA journal_mode = WAL;",
    "PRAGMA synchronous = NORMAL;",
    "PRAGMA foreign_keys = ON;",
    "PRAGMA busy_timeout = 5000;",
)

# Tables in this namespace are framework-owned. tracker_sql refuses DDL
# and write DML against them; SELECT is allowed so the queen can
# introspect the registry.
PROTECTED_PREFIX = "_"

# Cap on statements per execute_sql call. Bounds blast radius of a
# single tool call without being so low it forces awkward batching.
MAX_STATEMENTS_PER_CALL = 20

# Statement keywords rejected outright regardless of arguments.
_DENIED_LEADING_KEYWORDS = frozenset({"ATTACH", "DETACH", "PRAGMA", "VACUUM", "REINDEX"})

# Function calls forbidden anywhere in the SQL (after string/comment
# stripping). load_extension is the canonical SQLite footgun: it can
# load arbitrary shared libraries.
_DENIED_FUNCTIONS = ("load_extension",)

# Keywords that mean "this statement may write/structure-change". For
# these we additionally check the target table against PROTECTED_PREFIX.
_MUTATING_KEYWORDS = frozenset({"CREATE", "ALTER", "DROP", "INSERT", "UPDATE", "DELETE", "REPLACE", "TRUNCATE"})


class DenylistError(ValueError):
    """Raised when SQL is rejected by the denylist before execution."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with the standard pragmas applied.

    WAL mode is sticky on the file once set; the others are per-connection.
    ``isolation_level=None`` puts us in autocommit mode so the caller
    controls transactions explicitly with ``BEGIN``/``COMMIT``.
    """
    con = sqlite3.connect(str(db_path), isolation_level=None, timeout=5.0)
    for pragma in _PRAGMAS:
        con.execute(pragma)
    return con


def _quote_ident_db(name: str) -> str:
    """Quote a SQLite identifier (double the embedded double-quotes)."""
    return '"' + name.replace('"', '""') + '"'


def _quote_str(value: str) -> str:
    """Quote a SQL string literal (double the embedded single-quotes)."""
    return "'" + value.replace("'", "''") + "'"


def _change_trigger_names(table: str) -> tuple[str, str]:
    """(insert_trigger, update_trigger) names for ``table``.

    The ``_`` prefix puts them in the framework-owned namespace, so the
    denylist blocks the queen from dropping them.
    """
    return f"_tracker_chg__{table}__ins", f"_tracker_chg__{table}__upd"


def install_change_triggers(con: sqlite3.Connection, table: str, key_columns: list[str]) -> None:
    """(Re)create the AFTER INSERT/UPDATE change-log triggers on ``table``.

    The triggers live in the DB file itself, so every writer — worker
    upserts, queen raw SQL, UI row edits — is logged without any tool
    cooperation. Idempotent via DROP+CREATE so re-registration with new
    key_columns rebuilds the pk capture.
    """
    pk_expr = "json_object(" + ", ".join(f"{_quote_str(c)}, NEW.{_quote_ident_db(c)}" for c in key_columns) + ")"
    for trigger_name, op, event in (
        (_change_trigger_names(table)[0], "insert", "INSERT"),
        (_change_trigger_names(table)[1], "update", "UPDATE"),
    ):
        con.execute(f"DROP TRIGGER IF EXISTS {_quote_ident_db(trigger_name)}")
        con.execute(
            f"CREATE TRIGGER {_quote_ident_db(trigger_name)} "
            f"AFTER {event} ON {_quote_ident_db(table)} "
            "BEGIN "
            "INSERT INTO _tracker_changes (table_name, pk, op, changed_at) "
            f"VALUES ({_quote_str(table)}, {pk_expr}, {_quote_str(op)}, "
            "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')); "
            "END"
        )


def _backfill_change_triggers(con: sqlite3.Connection) -> None:
    """Install change triggers for every already-registered table.

    Runs on schema migration so colonies registered before the change
    log existed start logging without waiting for a re-registration.
    """
    try:
        rows = con.execute("SELECT table_name, key_columns FROM _tracker_registry").fetchall()
    except sqlite3.Error:
        return
    for table, key_json in rows:
        try:
            keys = [k for k in json.loads(key_json) if isinstance(k, str) and k]
        except (json.JSONDecodeError, TypeError):
            continue
        if not keys:
            continue
        exists = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if exists is None:
            continue
        try:
            install_change_triggers(con, table, keys)
        except sqlite3.Error as e:
            logger.warning("tracker_db: trigger backfill failed for '%s': %s", table, e)


def prune_change_log(con: sqlite3.Connection) -> None:
    """Drop change-log entries beyond the newest ``CHANGE_LOG_MAX``.

    Cheap when there is nothing to prune (indexed MAX + empty range
    delete), so callers run it opportunistically on write paths.
    """
    try:
        con.execute(
            "DELETE FROM _tracker_changes WHERE id <= (SELECT COALESCE(MAX(id), 0) FROM _tracker_changes) - ?",
            (CHANGE_LOG_MAX,),
        )
    except sqlite3.Error as e:
        logger.warning("tracker_db: change-log prune failed: %s", e)


# ---------------------------------------------------------------------------
# CRM promote-link: watermark diff between local work and team-CRM promotion
#
# The queen declares (once, via the crm_link tool) which local tracker table
# feeds the shared team CRM. From then on the framework can answer "how many
# rows changed since the last promotion?" with one local query: the change
# log (_tracker_changes) is an append-only, totally-ordered timeline, and
# the watermark below bookmarks the last observed scope='global' leads
# write. No global-DB query, no identity inference — the reminder only ever
# asserts what is locally provable.
# ---------------------------------------------------------------------------

# _tracker_meta keys. "crm_link" is the linked local table name, or the
# literal "none" for an explicit opt-out (non-GTM colony — never nag).
CRM_LINK_KEY = "crm_link"
CRM_WATERMARK_KEY = "crm_promoted_through"
CRM_PROMOTED_AT_KEY = "crm_promoted_at"
CRM_NUDGE_KEY = "crm_link_nudged"

CRM_OPT_OUT = "none"


def get_tracker_meta(con: sqlite3.Connection, key: str) -> str | None:
    row = con.execute("SELECT value FROM _tracker_meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_tracker_meta(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute(
        "INSERT OR REPLACE INTO _tracker_meta(key, value, updated_at) VALUES (?, ?, ?)",
        (key, value, _now_iso()),
    )


def crm_link_state(db_path: Path) -> dict[str, Any] | None:
    """Read the promote-link state. None on any error (advisory data —
    a busy/missing DB must never break a caller).

    Returns ``{"link": None | "none" | <table>, "watermark": int,
    "promoted_at": str | None, "nudged": bool}``.
    """
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0)
    except sqlite3.Error:
        return None
    try:
        return {
            "link": get_tracker_meta(con, CRM_LINK_KEY),
            "watermark": int(get_tracker_meta(con, CRM_WATERMARK_KEY) or 0),
            "promoted_at": get_tracker_meta(con, CRM_PROMOTED_AT_KEY),
            "nudged": get_tracker_meta(con, CRM_NUDGE_KEY) == "1",
        }
    except (sqlite3.Error, ValueError):
        return None
    finally:
        con.close()


def crm_unpromoted(db_path: Path) -> dict[str, Any] | None:
    """The watermark diff: distinct linked-table rows changed since the
    last observed promotion. None unless linked to a real table (or on
    any error).

    Returns ``{"table": str, "rows_changed": int,
    "last_change_age_s": float | None}``. ``last_change_age_s`` is how
    long ago the newest post-watermark change landed — the caller's
    quiescence signal (workers still writing => small age => hold the
    nudge until the run settles).
    """
    state = crm_link_state(db_path)
    if state is None or state["link"] in (None, CRM_OPT_OUT):
        return None
    table, watermark = state["link"], state["watermark"]
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0)
    except sqlite3.Error:
        return None
    try:
        row = con.execute(
            "SELECT COUNT(DISTINCT pk), MAX(changed_at) FROM _tracker_changes WHERE table_name = ? AND id > ?",
            (table, watermark),
        ).fetchone()
    except sqlite3.Error:
        return None
    finally:
        con.close()
    rows_changed = int(row[0] or 0)
    age: float | None = None
    if row[1]:
        try:
            last = datetime.strptime(str(row[1]), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            age = max(0.0, (datetime.now(UTC) - last).total_seconds())
        except ValueError:
            age = None
    return {"table": table, "rows_changed": rows_changed, "last_change_age_s": age}


def advance_crm_watermark(db_path: Path) -> bool:
    """Bookmark 'promoted through now': set the watermark to the change
    log's current MAX(id). Called when the runtime observes a scope=
    'global' write to the team CRM's ``leads``. Snapshotting the global
    max (not just the linked table's) is deliberate — a concurrent local
    write racing the promote lands on the *silent* side, so the reminder
    can under-report but never false-fire. No-op unless linked.
    """
    state = crm_link_state(db_path)
    if state is None or state["link"] in (None, CRM_OPT_OUT):
        return False
    try:
        con = _connect(Path(db_path))
    except sqlite3.Error:
        return False
    try:
        (max_id,) = con.execute("SELECT COALESCE(MAX(id), 0) FROM _tracker_changes").fetchone()
        set_tracker_meta(con, CRM_WATERMARK_KEY, str(int(max_id)))
        set_tracker_meta(con, CRM_PROMOTED_AT_KEY, _now_iso())
        return True
    except sqlite3.Error:
        return False
    finally:
        con.close()


def mark_crm_nudged(db_path: Path) -> None:
    """Persist that the one-time 'declare or opt out' nudge was sent."""
    try:
        con = _connect(Path(db_path))
    except sqlite3.Error:
        return
    try:
        set_tracker_meta(con, CRM_NUDGE_KEY, "1")
    except sqlite3.Error:
        pass
    finally:
        con.close()


def ensure_tracker_db(colony_dir: Path) -> Path:
    """Create or migrate ``{colony_dir}/tracker/tracker.db``.

    Idempotent: safe to call on an already-initialized DB. Returns the
    absolute path to the DB file.

    v3 moved the DB out of the ambiguous ``data/`` namespace into
    ``tracker/``; v2 layouts are migrated by ``migrate_v3.py`` on startup.
    """
    tracker_dir = Path(colony_dir) / "tracker"
    tracker_dir.mkdir(parents=True, exist_ok=True)
    db_path = tracker_dir / "tracker.db"

    con = _connect(db_path)
    try:
        current_version = con.execute("PRAGMA user_version").fetchone()[0]
        if current_version < SCHEMA_VERSION:
            con.executescript(_BOOTSTRAP_SCHEMA)
            con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            con.execute(
                "INSERT OR REPLACE INTO _tracker_meta(key, value, updated_at) VALUES (?, ?, ?)",
                ("schema_version", str(SCHEMA_VERSION), _now_iso()),
            )
            # Tables registered before the change log existed (schema < 3)
            # need their triggers created now.
            _backfill_change_triggers(con)
            logger.info("tracker_db: initialized schema v%d at %s", SCHEMA_VERSION, db_path)
        prune_change_log(con)
    finally:
        con.close()

    resolved = db_path.resolve()
    _patch_worker_configs(Path(colony_dir), resolved)
    return resolved


def _patch_worker_configs(colony_dir: Path, tracker_db_path: Path) -> int:
    """Rewrite each worker.json's ``input_data`` to contain a fresh
    :class:`ColonyBinding` (and strip legacy ProgressDB/loose-path fields).

    Runs on every ``ensure_tracker_db`` call so worker configs always
    carry the current binding for the colony. Returns the number of files
    modified.
    """
    binding_payload = {
        "name": colony_dir.name,
        "dir": str(colony_dir),
        "tracker_db": str(tracker_db_path),
    }
    patched = 0

    for worker_cfg in colony_dir.glob("*.json"):
        # Skip colony-level files.
        if worker_cfg.name in ("metadata.json", "triggers.json"):
            continue
        try:
            data = json.loads(worker_cfg.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict) or "system_prompt" not in data:
            continue

        input_data = data.get("input_data")
        if not isinstance(input_data, dict):
            input_data = {}

        changed = False
        if input_data.get("binding") != binding_payload:
            input_data["binding"] = binding_payload
            changed = True
        for legacy_key in ("db_path", "colony_data_dir", "tracker_db_path", "colony_id"):
            if legacy_key in input_data:
                input_data.pop(legacy_key, None)
                changed = True
        if not changed:
            continue  # already patched

        data["input_data"] = input_data

        try:
            worker_cfg.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            patched += 1
        except OSError as e:
            logger.warning("tracker_db: failed to patch worker config %s: %s", worker_cfg, e)

    if patched:
        logger.info(
            "tracker_db: patched %d worker config(s) in colony '%s' with fresh binding",
            patched,
            colony_dir.name,
        )
    return patched


def ensure_all_colony_tracker_dbs(colonies_root: Path | None = None) -> list[Path]:
    """Idempotently ensure every existing colony has a tracker.db.

    Called on framework host startup to backfill colonies that were
    forked before TrackerDB landed.
    """
    if colonies_root is None:
        from framework.config import COLONIES_DIR

        colonies_root = COLONIES_DIR
    if not colonies_root.is_dir():
        return []

    initialized: list[Path] = []
    for entry in sorted(colonies_root.iterdir()):
        if not entry.is_dir():
            continue
        try:
            initialized.append(ensure_tracker_db(entry))
        except Exception as e:
            logger.warning("tracker_db: failed to ensure DB for colony '%s': %s", entry.name, e)
    return initialized


# ---------------------------------------------------------------------------
# Denylist parser
# ---------------------------------------------------------------------------


def _strip_strings_and_comments(sql: str) -> str:
    """Return SQL with string literals and comments replaced by spaces.

    Used for keyword scans where we must not match keywords that appear
    inside string contents (``'... ATTACH ...'``) or comments.

    Handles:
      - line comments: ``-- ... \\n``
      - block comments: ``/* ... */`` (non-nesting, like SQLite)
      - single-quoted strings with ``''`` escape: ``'O''Brien'``

    Double-quoted ``"col"`` and bracket-quoted ``[col]`` identifiers are
    left intact so that the table-name extractor can still see them.
    """
    out: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        c = sql[i]
        if c == "-" and i + 1 < n and sql[i + 1] == "-":
            j = sql.find("\n", i)
            if j == -1:
                break
            out.append(" ")
            i = j + 1
            continue
        if c == "/" and i + 1 < n and sql[i + 1] == "*":
            j = sql.find("*/", i + 2)
            if j == -1:
                # Unterminated comment; bail. SQLite would reject this too.
                break
            # A single space, not nothing: a comment glued between tokens
            # (``INSERT INTO/**/_tbl``) must not fuse them into one token.
            out.append(" ")
            i = j + 2
            continue
        if c == "'":
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        j += 2
                        continue
                    break
                j += 1
            out.append(" ")
            i = j + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _has_executable_content(stmt: str) -> bool:
    """True if the statement contains anything beyond comments/whitespace."""
    return bool(_strip_strings_and_comments(stmt).strip())


def _split_statements(sql: str) -> list[str]:
    """Split SQL on top-level ``;`` (outside strings and comments).

    Returns the *original* statement text (strings and comments preserved)
    so that the executor sees what the caller wrote. Comment-only chunks
    are skipped — they're not executable statements. Only the splitting
    logic looks past quotes/comments; the returned slices are verbatim.
    """
    statements: list[str] = []
    current: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        c = sql[i]
        # Line comment: keep verbatim, copy up to and including newline.
        if c == "-" and i + 1 < n and sql[i + 1] == "-":
            j = sql.find("\n", i)
            if j == -1:
                current.append(sql[i:])
                i = n
                continue
            current.append(sql[i : j + 1])
            i = j + 1
            continue
        # Block comment: keep verbatim through ``*/``.
        if c == "/" and i + 1 < n and sql[i + 1] == "*":
            j = sql.find("*/", i + 2)
            if j == -1:
                current.append(sql[i:])
                i = n
                continue
            current.append(sql[i : j + 2])
            i = j + 2
            continue
        # Single-quoted string with '' escape: copy verbatim.
        if c == "'":
            current.append("'")
            j = i + 1
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        current.append("''")
                        j += 2
                        continue
                    current.append("'")
                    j += 1
                    break
                current.append(sql[j])
                j += 1
            i = j
            continue
        if c == ";":
            stmt = "".join(current).strip()
            if stmt and _has_executable_content(stmt):
                statements.append(stmt)
            current = []
            i += 1
            continue
        current.append(c)
        i += 1
    tail = "".join(current).strip()
    if tail and _has_executable_content(tail):
        statements.append(tail)
    return statements


def _leading_keyword(stmt: str) -> str:
    """First whitespace-delimited token of a statement, uppercased.

    Computed on the string/comment-stripped view so a leading comment
    (``/* x */ PRAGMA ...``) cannot mask the keyword.
    """
    for token in _strip_strings_and_comments(stmt).split():
        return token.upper()
    return ""


def _top_level_words(cleaned: str) -> list[tuple[str, int]]:
    """(word, start_offset) pairs for word tokens at paren depth 0.

    ``cleaned`` must already be string/comment-stripped. Words inside
    parentheses (CTE bodies, column lists, subqueries) are skipped so
    callers see only the statement's own top-level keywords.
    """
    words: list[tuple[str, int]] = []
    depth = 0
    start: int | None = None

    def flush(end: int) -> None:
        nonlocal start
        if start is not None:
            words.append((cleaned[start:end], start))
            start = None

    for i, ch in enumerate(cleaned):
        if ch == "(":
            flush(i)
            depth += 1
        elif ch == ")":
            start = None
            depth = max(0, depth - 1)
        elif depth == 0 and (ch.isalnum() or ch == "_"):
            if start is None:
                start = i
        else:
            flush(i)
    flush(len(cleaned))
    return words


# Keywords that can start the main clause of a WITH-prefixed statement.
_WITH_MAIN_VERBS = frozenset({"SELECT", "VALUES", "INSERT", "UPDATE", "DELETE", "REPLACE"})


def _effective_statement(stmt: str) -> tuple[str, str]:
    """Resolve a statement to ``(effective_verb, policy_body)``.

    Both derive from the string/comment-stripped view. For most
    statements the verb is simply the first token. For ``WITH``-prefixed
    statements the verb is the first top-level main-clause keyword after
    the CTE list — SQLite allows ``WITH ... INSERT/UPDATE/DELETE``, so
    trusting the leading ``WITH`` would misclassify writes as reads.
    ``policy_body`` starts at the verb so table extraction sees the DML
    clause, not the CTE definitions. When no main verb is found the verb
    stays ``WITH`` (malformed SQL; SQLite rejects it at execute time,
    and read-only gates reject it up front).
    """
    cleaned = _strip_strings_and_comments(stmt)
    words = _top_level_words(cleaned)
    if not words:
        return "", cleaned
    first_word, first_pos = words[0]
    verb = first_word.upper()
    if verb != "WITH":
        return verb, cleaned[first_pos:]
    for word, pos in words[1:]:
        up = word.upper()
        if up in _WITH_MAIN_VERBS:
            return up, cleaned[pos:]
    return verb, cleaned


def _strip_identifier(name: str) -> str:
    """Strip common identifier quoting/punctuation so we can compare names."""
    # Trailing punctuation from tokenization (commas, parens, semicolons)
    # plus identifier quote characters: backtick, double-quote, square brackets.
    return name.strip('`"[](),;')


def _referenced_tables_for_mutation(stmt: str) -> list[str]:
    """Best-effort extraction of table names targeted by a mutating stmt.

    Used to enforce ``PROTECTED_PREFIX``. Conservative: when we can't tell,
    we return nothing and let the SQL through. The protection here is
    defense-in-depth — workers' ``tracker_upsert`` independently refuses
    ``_*`` tables, and the queen has no legitimate reason to drop the
    registry (she has a tracker_register_writable helper for it).
    """
    tokens = stmt.split()
    if not tokens:
        return []
    head = tokens[0].upper()
    rest = tokens[1:]
    rest_upper = [t.upper() for t in rest]

    if head in ("INSERT", "REPLACE"):
        # INSERT [OR REPLACE|IGNORE|...] INTO <name>
        for i, t in enumerate(rest_upper):
            if t == "INTO" and i + 1 < len(rest):
                return [_strip_identifier(rest[i + 1])]
        return []

    if head == "UPDATE":
        # UPDATE [OR REPLACE|IGNORE|...] <name> SET ...
        i = 0
        if rest_upper[:1] == ["OR"] and len(rest_upper) >= 2:
            i = 2
        if i < len(rest):
            return [_strip_identifier(rest[i])]
        return []

    if head == "DELETE":
        # DELETE FROM <name>
        for i, t in enumerate(rest_upper):
            if t == "FROM" and i + 1 < len(rest):
                return [_strip_identifier(rest[i + 1])]
        return []

    if head == "TRUNCATE":
        # SQLite doesn't have TRUNCATE but reject for safety; treat
        # ``TRUNCATE [TABLE] <name>`` just in case.
        i = 0
        if rest_upper[:1] == ["TABLE"]:
            i = 1
        if i < len(rest):
            return [_strip_identifier(rest[i])]
        return []

    if head in ("CREATE", "DROP", "ALTER"):
        # Walk past optional modifiers: TEMP/TEMPORARY/UNIQUE/VIRTUAL.
        i = 0
        while i < len(rest_upper) and rest_upper[i] in (
            "TEMP",
            "TEMPORARY",
            "UNIQUE",
            "VIRTUAL",
        ):
            i += 1
        if i >= len(rest_upper):
            return []
        kind = rest_upper[i]
        if kind not in ("TABLE", "INDEX", "VIEW", "TRIGGER"):
            return []
        i += 1
        # Skip IF [NOT] EXISTS
        if rest_upper[i : i + 3] == ["IF", "NOT", "EXISTS"]:
            i += 3
        elif rest_upper[i : i + 2] == ["IF", "EXISTS"]:
            i += 2
        names: list[str] = []
        if i < len(rest):
            names.append(_strip_identifier(rest[i]))
        # CREATE INDEX <idx> ON <table>: protect the target table too.
        if kind == "INDEX":
            for j in range(i + 1, len(rest_upper)):
                if rest_upper[j] == "ON" and j + 1 < len(rest):
                    names.append(_strip_identifier(rest[j + 1]))
                    break
        # CREATE TRIGGER <trg> ... ON <table>: protect target table.
        if kind == "TRIGGER":
            for j in range(i + 1, len(rest_upper)):
                if rest_upper[j] == "ON" and j + 1 < len(rest):
                    names.append(_strip_identifier(rest[j + 1]))
                    break
        return [n for n in names if n]

    return []


def validate_sql(sql: str) -> None:
    """Raise :class:`DenylistError` if ``sql`` violates tracker policy.

    Policy is documented at the top of this module. Raises before any
    statement is executed; the SQL is either fully accepted or fully
    rejected (no partial execution).
    """
    if not sql or not sql.strip():
        raise DenylistError("empty SQL")

    statements = _split_statements(sql)
    if not statements:
        raise DenylistError("no executable statements")
    if len(statements) > MAX_STATEMENTS_PER_CALL:
        raise DenylistError(f"too many statements: {len(statements)} > {MAX_STATEMENTS_PER_CALL}")

    # Function-level denylist scan, on a string/comment-stripped lowercase
    # view so keywords inside literals don't false-match.
    cleaned = _strip_strings_and_comments(sql).lower()
    for fn in _DENIED_FUNCTIONS:
        idx = 0
        while True:
            pos = cleaned.find(fn, idx)
            if pos == -1:
                break
            # Must be a function call (followed by `(`) and a word-boundary
            # before (no preceding identifier char).
            before_ok = pos == 0 or not (cleaned[pos - 1].isalnum() or cleaned[pos - 1] == "_")
            after = cleaned[pos + len(fn) :].lstrip()
            if before_ok and after.startswith("("):
                raise DenylistError(f"forbidden function: {fn}()")
            idx = pos + len(fn)

    # Per-statement effective-verb + protected-table check, on the
    # stripped view so comments can't hide keywords and WITH-prefixed
    # DML resolves to its real verb instead of reading as "WITH".
    for stmt in statements:
        verb, body = _effective_statement(stmt)
        if verb in _DENIED_LEADING_KEYWORDS:
            raise DenylistError(f"forbidden statement: {verb}")
        if verb in _MUTATING_KEYWORDS:
            for tbl in _referenced_tables_for_mutation(body):
                if tbl.startswith(PROTECTED_PREFIX):
                    raise DenylistError(f"forbidden mutation on framework table: {tbl}")


def execute_sql(
    db_path: Path,
    sql: str,
    *,
    row_cap: int = 1000,
) -> dict[str, Any]:
    """Validate and execute SQL on ``tracker.db``.

    Single-statement returns:
      - read (cursor.description is not None):
          ``{"kind": "rows", "columns": [...], "rows": [[...], ...],
             "rowcount": int, "truncated": bool}``
      - write/DDL:
          ``{"kind": "exec", "rowcount": int, "last_insert_rowid": int}``

    Multi-statement returns:
      ``{"kind": "script", "results": [<single-stmt result>, ...]}``

    Rows are returned as plain lists (JSON-serialisable). Anything past
    ``row_cap`` is dropped and ``truncated`` is set to True; the caller
    can paginate with LIMIT/OFFSET.
    """
    validate_sql(sql)
    statements = _split_statements(sql)

    con = _connect(Path(db_path))
    try:
        results: list[dict[str, Any]] = []
        for stmt in statements:
            cur = con.execute(stmt)
            if cur.description is not None:
                cols = [c[0] for c in cur.description]
                rows: list[list[Any]] = []
                truncated = False
                fetched = 0
                for row in cur:
                    if fetched >= row_cap:
                        truncated = True
                        break
                    rows.append(list(row))
                    fetched += 1
                results.append(
                    {
                        "kind": "rows",
                        "columns": cols,
                        "rows": rows,
                        "rowcount": fetched,
                        "truncated": truncated,
                    }
                )
            else:
                results.append(
                    {
                        "kind": "exec",
                        "rowcount": cur.rowcount,
                        "last_insert_rowid": cur.lastrowid,
                    }
                )
        if len(results) == 1:
            return results[0]
        return {"kind": "script", "results": results}
    finally:
        con.close()


__all__ = [
    "CHANGE_LOG_MAX",
    "CRM_LINK_KEY",
    "CRM_NUDGE_KEY",
    "CRM_OPT_OUT",
    "CRM_PROMOTED_AT_KEY",
    "CRM_WATERMARK_KEY",
    "SCHEMA_VERSION",
    "DenylistError",
    "MAX_STATEMENTS_PER_CALL",
    "PROTECTED_PREFIX",
    "advance_crm_watermark",
    "crm_link_state",
    "crm_unpromoted",
    "ensure_all_colony_tracker_dbs",
    "ensure_tracker_db",
    "execute_sql",
    "get_tracker_meta",
    "install_change_triggers",
    "mark_crm_nudged",
    "prune_change_log",
    "set_tracker_meta",
    "validate_sql",
]
