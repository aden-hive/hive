"""Tests for framework.host.tracker_db — per-colony queen-owned domain DB.

Three concerns:
1. Lifecycle (``ensure_tracker_db``): file creation, WAL, schema version,
   bootstrap tables, idempotency.
2. Denylist (``validate_sql``): allow/reject parity with the documented
   policy. String- and comment-aware so we don't false-positive on
   keywords inside literals.
3. Execute (``execute_sql``): roundtrip on real SQLite, row-cap
   truncation, multi-statement scripts.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from framework.host.tracker_db import (
    CHANGE_LOG_MAX,
    MAX_STATEMENTS_PER_CALL,
    SCHEMA_VERSION,
    DenylistError,
    ensure_all_colony_tracker_dbs,
    ensure_tracker_db,
    execute_sql,
    prune_change_log,
    validate_sql,
)

# ----------------------------------------------------------------------
# Lifecycle
# ----------------------------------------------------------------------


def test_ensure_tracker_db_fresh(tmp_path: Path) -> None:
    colony = tmp_path / "c"
    db_path = ensure_tracker_db(colony)

    assert db_path.exists()
    assert db_path.name == "tracker.db"
    assert db_path.parent.name == "tracker"

    con = sqlite3.connect(str(db_path))
    try:
        assert con.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert con.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"_tracker_registry", "_tracker_meta"}.issubset(tables)

        # Schema version is also recorded in _tracker_meta for visibility
        # outside of PRAGMA.
        row = con.execute("SELECT value FROM _tracker_meta WHERE key='schema_version'").fetchone()
        assert row is not None and row[0] == str(SCHEMA_VERSION)
    finally:
        con.close()


def test_ensure_tracker_db_idempotent(tmp_path: Path) -> None:
    colony = tmp_path / "c"
    p1 = ensure_tracker_db(colony)
    p2 = ensure_tracker_db(colony)
    assert p1 == p2

    # Still on the expected schema version after the second call (i.e. we
    # don't accidentally re-bootstrap and clobber state).
    con = sqlite3.connect(str(p1))
    try:
        assert con.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        con.close()


def test_ensure_tracker_db_preserves_user_data(tmp_path: Path) -> None:
    """Re-running ensure_tracker_db must not drop queen-created tables."""
    colony = tmp_path / "c"
    db_path = ensure_tracker_db(colony)

    con = sqlite3.connect(str(db_path))
    try:
        con.execute("CREATE TABLE competitors (name TEXT PRIMARY KEY, url TEXT)")
        con.execute("INSERT INTO competitors VALUES ('acme', 'https://acme.test')")
        con.commit()
    finally:
        con.close()

    ensure_tracker_db(colony)  # second call must be a no-op for user data

    con = sqlite3.connect(str(db_path))
    try:
        row = con.execute("SELECT name, url FROM competitors").fetchone()
        assert row == ("acme", "https://acme.test")
    finally:
        con.close()


def test_migration_backfills_change_triggers(tmp_path: Path) -> None:
    """Colonies registered before the change log existed (schema v2) must
    start logging on migration — without waiting for a re-registration
    that may never happen."""
    colony = tmp_path / "c"
    tracker_dir = colony / "tracker"
    tracker_dir.mkdir(parents=True)
    db = tracker_dir / "tracker.db"
    con = sqlite3.connect(str(db))
    con.executescript(
        """
        CREATE TABLE _tracker_registry (
            table_name TEXT PRIMARY KEY, write_columns TEXT NOT NULL,
            key_columns TEXT NOT NULL, mode TEXT NOT NULL, registered_at TEXT NOT NULL
        );
        CREATE TABLE _tracker_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE leads (id TEXT PRIMARY KEY, v TEXT);
        INSERT INTO _tracker_registry VALUES ('leads', '["v"]', '["id"]', 'upsert', 'x');
        PRAGMA user_version = 2;
        """
    )
    con.close()

    ensure_tracker_db(colony)

    con = sqlite3.connect(str(db))
    try:
        triggers = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        assert {"_tracker_chg__leads__ins", "_tracker_chg__leads__upd"} <= triggers
        # And they actually log: a plain INSERT lands in _tracker_changes
        # with the row's pk captured as JSON.
        con.execute("INSERT INTO leads VALUES ('a', '1')")
        con.commit()
        row = con.execute("SELECT table_name, pk, op FROM _tracker_changes").fetchone()
        assert row == ("leads", '{"id":"a"}', "insert")
    finally:
        con.close()


def test_prune_change_log_caps_entries(tmp_path: Path) -> None:
    """The change log must stay bounded — the snapshot read path byte-copies
    the whole file, so unbounded growth taxes every UI poll."""
    colony = tmp_path / "c"
    db_path = ensure_tracker_db(colony)
    con = sqlite3.connect(str(db_path))
    try:
        con.executemany(
            "INSERT INTO _tracker_changes (table_name, pk, op, changed_at) VALUES ('t', '{}', 'insert', 'x')",
            [()] * (CHANGE_LOG_MAX + 50),
        )
        con.commit()
        prune_change_log(con)
        count = con.execute("SELECT COUNT(*) FROM _tracker_changes").fetchone()[0]
        assert count == CHANGE_LOG_MAX
        # Newest entries survive, oldest are dropped.
        min_id = con.execute("SELECT MIN(id) FROM _tracker_changes").fetchone()[0]
        assert min_id == 51
    finally:
        con.close()


# ----------------------------------------------------------------------
# Denylist — allowed cases
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE competitors (name TEXT PRIMARY KEY, url TEXT)",
        "CREATE TABLE IF NOT EXISTS x (a INTEGER)",
        "ALTER TABLE competitors ADD COLUMN pricing TEXT",
        "DROP TABLE competitors",
        "DROP TABLE IF EXISTS competitors",
        "CREATE INDEX idx_x ON competitors (name)",
        "CREATE UNIQUE INDEX idx_y ON competitors (url)",
        "CREATE VIEW v AS SELECT name FROM competitors",
        "INSERT INTO competitors VALUES ('a', 'b')",
        "INSERT OR REPLACE INTO competitors VALUES ('a', 'b')",
        "UPDATE competitors SET url = 'x' WHERE name = 'a'",
        "DELETE FROM competitors WHERE name = 'a'",
        "SELECT * FROM competitors",
        "SELECT * FROM _tracker_registry",  # SELECT from protected is OK
        "WITH cte AS (SELECT 1) SELECT * FROM cte",
        # WITH-prefixed DML on a *user* table is legitimate queen SQL —
        # the verb resolver must not over-reject it.
        "WITH doomed AS (SELECT 1) DELETE FROM competitors",
        "BEGIN; INSERT INTO t VALUES (1); COMMIT",
        # Keywords inside string literals must NOT trigger the denylist.
        "INSERT INTO t VALUES ('ATTACH something dangerous')",
        "INSERT INTO t VALUES ('PRAGMA foreign_keys=OFF')",
        # Keywords inside comments must NOT trigger.
        "-- VACUUM is forbidden but this is a comment\nSELECT 1",
        "/* PRAGMA test */ SELECT 1",
    ],
)
def test_validate_sql_allows(sql: str) -> None:
    validate_sql(sql)  # must not raise


# ----------------------------------------------------------------------
# Denylist — rejected cases
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql,fragment",
    [
        ("ATTACH DATABASE 'other.db' AS other", "ATTACH"),
        ("DETACH DATABASE other", "DETACH"),
        ("PRAGMA foreign_keys = OFF", "PRAGMA"),
        ("PRAGMA table_info(x)", "PRAGMA"),  # no readonly whitelist
        ("VACUUM", "VACUUM"),
        ("REINDEX", "REINDEX"),
        # A leading comment must not mask the keyword — the check runs on
        # the comment-stripped view, else `/* x */ PRAGMA ...` slips through.
        ("/* hi */ PRAGMA journal_mode = DELETE", "PRAGMA"),
        ("-- hi\nVACUUM", "VACUUM"),
    ],
)
def test_validate_sql_rejects_leading_keywords(sql: str, fragment: str) -> None:
    with pytest.raises(DenylistError, match=fragment):
        validate_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT load_extension('evil.so')",
        "SELECT load_extension ('evil.so')",  # spaces before paren
        "SELECT LOAD_EXTENSION('evil.so')",  # case-insensitive
        "INSERT INTO t SELECT load_extension('x')",
    ],
)
def test_validate_sql_rejects_load_extension(sql: str) -> None:
    with pytest.raises(DenylistError, match="load_extension"):
        validate_sql(sql)


def test_validate_sql_load_extension_in_string_is_ok() -> None:
    # The literal token "load_extension" inside a string literal must not
    # trigger the denylist — it's data, not code.
    validate_sql("INSERT INTO t VALUES ('load_extension(x)')")


def test_validate_sql_load_extension_as_substring_is_ok() -> None:
    # ``my_load_extension`` is a different identifier; word-boundary check
    # must not false-positive.
    validate_sql("SELECT my_load_extension(1)")


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE _tracker_registry",
        "DROP TABLE IF EXISTS _tracker_registry",
        "CREATE TABLE _hidden (a INTEGER)",
        "ALTER TABLE _tracker_meta ADD COLUMN x TEXT",
        "INSERT INTO _tracker_registry VALUES ('x','[]','[]','upsert','now')",
        "UPDATE _tracker_registry SET mode='append'",
        "DELETE FROM _tracker_meta",
        # Bracket-quoted identifier: still must be caught.
        "DROP TABLE [_tracker_registry]",
        # Backtick-quoted identifier.
        "DROP TABLE `_tracker_registry`",
        # CREATE INDEX whose target table is protected.
        "CREATE INDEX idx_evil ON _tracker_registry (table_name)",
        # WITH-prefixed DML: SQLite allows ``WITH ... DELETE/INSERT/UPDATE``,
        # so the protected check must resolve the real verb, not stop at WITH.
        "WITH x AS (SELECT 1) DELETE FROM _tracker_registry",
        "WITH x AS (SELECT 1) INSERT INTO _tracker_registry SELECT * FROM x",
        "WITH x AS (SELECT 1) UPDATE _tracker_meta SET value='p'",
        # A comment glued between tokens must not fuse them and hide the
        # target table from extraction.
        "INSERT INTO/**/_tracker_registry VALUES ('x','[]','[]','upsert','now')",
        # A leading comment must not mask the mutation keyword.
        "/* hi */ DROP TABLE _tracker_registry",
        # Change-log triggers are framework-owned; the queen must not be
        # able to disable row-level tracking by dropping them.
        "DROP TRIGGER _tracker_chg__leads__ins",
        'DROP TRIGGER "_tracker_chg__leads__upd"',
    ],
)
def test_validate_sql_rejects_protected_namespace(sql: str) -> None:
    with pytest.raises(DenylistError, match="framework table"):
        validate_sql(sql)


def test_validate_sql_rejects_empty() -> None:
    with pytest.raises(DenylistError, match="empty"):
        validate_sql("")
    with pytest.raises(DenylistError, match="empty"):
        validate_sql("   \n  ")


def test_validate_sql_rejects_only_comments() -> None:
    with pytest.raises(DenylistError, match="no executable"):
        validate_sql("-- nothing here\n")


def test_validate_sql_rejects_too_many_statements() -> None:
    sql = "; ".join(["SELECT 1"] * (MAX_STATEMENTS_PER_CALL + 1))
    with pytest.raises(DenylistError, match="too many"):
        validate_sql(sql)


def test_validate_sql_string_with_semicolon_does_not_split() -> None:
    # Semicolons inside string literals must not trick the splitter into
    # producing extra (potentially-allowed) statements.
    validate_sql("INSERT INTO t VALUES ('a;b;c')")


def test_validate_sql_rejects_one_bad_in_script() -> None:
    # If any statement in a multi-statement script violates, the whole
    # call is rejected (no partial execution).
    sql = "CREATE TABLE good (a INT); ATTACH DATABASE 'x' AS y; SELECT 1"
    with pytest.raises(DenylistError, match="ATTACH"):
        validate_sql(sql)


# ----------------------------------------------------------------------
# execute_sql — roundtrip
# ----------------------------------------------------------------------


def test_execute_sql_create_insert_select(tmp_path: Path) -> None:
    db = ensure_tracker_db(tmp_path / "c")

    r = execute_sql(db, "CREATE TABLE competitors (name TEXT PRIMARY KEY, url TEXT)")
    assert r["kind"] == "exec"

    r = execute_sql(db, "INSERT INTO competitors VALUES ('acme', 'https://acme.test')")
    assert r["kind"] == "exec"
    assert r["rowcount"] == 1

    r = execute_sql(db, "SELECT name, url FROM competitors")
    assert r["kind"] == "rows"
    assert r["columns"] == ["name", "url"]
    assert r["rows"] == [["acme", "https://acme.test"]]
    assert r["rowcount"] == 1
    assert r["truncated"] is False


def test_execute_sql_multi_statement_script(tmp_path: Path) -> None:
    db = ensure_tracker_db(tmp_path / "c")
    sql = "CREATE TABLE x (a INTEGER);INSERT INTO x VALUES (1);INSERT INTO x VALUES (2);SELECT a FROM x ORDER BY a"
    r = execute_sql(db, sql)
    assert r["kind"] == "script"
    assert len(r["results"]) == 4
    assert r["results"][-1]["kind"] == "rows"
    assert r["results"][-1]["rows"] == [[1], [2]]


def test_execute_sql_truncation(tmp_path: Path) -> None:
    db = ensure_tracker_db(tmp_path / "c")
    execute_sql(db, "CREATE TABLE x (a INTEGER)")
    # Seed 5 rows.
    execute_sql(
        db,
        "INSERT INTO x VALUES (1); INSERT INTO x VALUES (2); INSERT INTO x VALUES (3); INSERT INTO x VALUES (4); INSERT INTO x VALUES (5)",
    )
    r = execute_sql(db, "SELECT a FROM x ORDER BY a", row_cap=3)
    assert r["kind"] == "rows"
    assert len(r["rows"]) == 3
    assert r["truncated"] is True


def test_execute_sql_rejects_before_running(tmp_path: Path) -> None:
    db = ensure_tracker_db(tmp_path / "c")
    # Script with one allowed and one denied stmt; the allowed one must
    # NOT run because validation fires first.
    sql = "CREATE TABLE will_not_be_made (a INTEGER); ATTACH DATABASE 'x' AS y"
    with pytest.raises(DenylistError):
        execute_sql(db, sql)

    con = sqlite3.connect(str(db))
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "will_not_be_made" not in tables
    finally:
        con.close()


def test_execute_sql_select_from_protected_works(tmp_path: Path) -> None:
    """The queen must be able to introspect _tracker_registry via SELECT."""
    db = ensure_tracker_db(tmp_path / "c")
    r = execute_sql(db, "SELECT table_name FROM _tracker_registry")
    assert r["kind"] == "rows"
    assert r["columns"] == ["table_name"]
    assert r["rows"] == []  # nothing registered yet


# ----------------------------------------------------------------------
# Worker-config patching + multi-colony backfill
# ----------------------------------------------------------------------


def _make_worker_cfg(colony_dir: Path, name: str = "worker", **overrides) -> Path:
    """Write a minimal worker-config-shaped JSON for patcher tests."""
    colony_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "name": name,
        "system_prompt": "you are a worker",
        "tools": [],
        "input_data": {},
    }
    data.update(overrides)
    p = colony_dir / f"{name}.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_ensure_tracker_db_patches_existing_worker_config(tmp_path: Path) -> None:
    colony = tmp_path / "c"
    cfg = _make_worker_cfg(colony, input_data={"db_path": "/x/progress.db"})

    db_path = ensure_tracker_db(colony)

    patched = json.loads(cfg.read_text(encoding="utf-8"))
    # input_data now carries a ColonyBinding dict, not loose path fields.
    binding = patched["input_data"]["binding"]
    assert binding["tracker_db"] == str(db_path)
    assert binding["name"] == colony.name
    # Legacy ProgressDB / loose-path context is removed.
    assert "db_path" not in patched["input_data"]


def test_patch_worker_configs_idempotent(tmp_path: Path) -> None:
    colony = tmp_path / "c"
    cfg = _make_worker_cfg(colony)
    db_path = ensure_tracker_db(colony)
    mtime_after_first = cfg.stat().st_mtime_ns
    # Re-running ensure_tracker_db must NOT rewrite an already-patched file.
    ensure_tracker_db(colony)
    assert cfg.stat().st_mtime_ns == mtime_after_first
    patched = json.loads(cfg.read_text(encoding="utf-8"))
    assert patched["input_data"]["binding"]["tracker_db"] == str(db_path)


def test_patch_worker_configs_skips_colony_level_files(tmp_path: Path) -> None:
    colony = tmp_path / "c"
    colony.mkdir()
    # These two colony-level files must NOT be touched even though they're *.json.
    metadata = colony / "metadata.json"
    metadata.write_text(json.dumps({"colony_id": "c"}), encoding="utf-8")
    triggers = colony / "triggers.json"
    triggers.write_text(json.dumps([]), encoding="utf-8")

    ensure_tracker_db(colony)

    assert json.loads(metadata.read_text(encoding="utf-8")) == {"colony_id": "c"}
    assert json.loads(triggers.read_text(encoding="utf-8")) == []


def test_patch_worker_configs_skips_non_worker_shaped(tmp_path: Path) -> None:
    """Files that lack the worker_meta shape (no system_prompt) must be left alone."""
    colony = tmp_path / "c"
    colony.mkdir()
    other = colony / "random.json"
    other.write_text(json.dumps({"unrelated": True}), encoding="utf-8")

    ensure_tracker_db(colony)

    data = json.loads(other.read_text(encoding="utf-8"))
    assert data == {"unrelated": True}


def test_ensure_all_colony_tracker_dbs_backfill(tmp_path: Path) -> None:
    colonies_root = tmp_path / "colonies"
    (colonies_root / "alpha").mkdir(parents=True)
    (colonies_root / "beta").mkdir(parents=True)
    (colonies_root / "gamma_not_dir").touch()  # ignored

    initialized = ensure_all_colony_tracker_dbs(colonies_root)
    names = {p.parent.parent.name for p in initialized}
    assert names == {"alpha", "beta"}
    for p in initialized:
        assert p.exists()
        assert p.name == "tracker.db"


def test_ensure_all_colony_tracker_dbs_missing_root(tmp_path: Path) -> None:
    assert ensure_all_colony_tracker_dbs(tmp_path / "nonexistent") == []
