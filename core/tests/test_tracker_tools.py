"""Tests for framework.tools.tracker_tools — queen + worker tracker tools.

Covers:
  - Path resolution from execution context (tracker_db_path / colony_id)
  - tracker_sql: roundtrip + denylist passthrough
  - tracker_register_writable: validation (existence, columns, unique idx)
  - tracker_upsert: registry-gated, mode-aware, scoped writes
  - QUEEN_ONLY_TRACKER_TOOLS / register_tracker_tools wiring

Tests publish an execution context via ``ToolRegistry.set_execution_context``
because the tracker tools resolve the DB path from that context (same
pattern the runtime uses to scope task tools per agent).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from framework.host.tracker_db import ensure_tracker_db
from framework.loader.tool_registry import ToolRegistry, _execution_context
from framework.tools.tracker_tools import (
    QUEEN_ONLY_TRACKER_TOOLS,
    build_tracker_tools,
    register_tracker_tools,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _executors() -> dict:
    """Pull (tool_name → async-executor) pairs from build_tracker_tools."""
    return {tool.name: ex for tool, ex in build_tracker_tools()}


@pytest.fixture
def colony(tmp_path: Path) -> Path:
    """Materialize a colony directory with tracker.db and return the colony dir."""
    cdir = tmp_path / "test_colony"
    ensure_tracker_db(cdir)
    return cdir


@pytest.fixture
def with_ctx(colony: Path):
    """Publish an execution context with tracker_db_path pointing at colony.

    Yields the colony tracker.db path. Resets the contextvar afterwards.
    """
    db_path = colony / "data" / "tracker.db"
    token = ToolRegistry.set_execution_context(
        agent_id="test-agent",
        colony_id=colony.name,
        tracker_db_path=str(db_path),
    )
    try:
        yield db_path
    finally:
        ToolRegistry.reset_execution_context(token)


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_colony_context_returns_clear_error() -> None:
    # Empty context — neither colony_id nor tracker_db_path set.
    token = _execution_context.set({})
    try:
        ex = _executors()["tracker_sql"]
        r = await ex({"sql": "SELECT 1"})
        assert r["success"] is False
        assert "no colony context" in r["error"]
    finally:
        _execution_context.reset(token)


@pytest.mark.asyncio
async def test_resolves_via_colony_id_when_path_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """When tracker_db_path is absent, fall back to COLONIES_DIR/colony_id/data/tracker.db."""
    monkeypatch.setattr("framework.config.COLONIES_DIR", tmp_path)
    cdir = tmp_path / "research"
    ensure_tracker_db(cdir)

    token = ToolRegistry.set_execution_context(colony_id="research", agent_id="a")
    try:
        r = await _executors()["tracker_sql"]({"sql": "SELECT 1 AS x"})
        assert r["success"] is True
        assert r["kind"] == "rows"
        assert r["columns"] == ["x"]
        assert r["rows"] == [[1]]
    finally:
        ToolRegistry.reset_execution_context(token)


# ---------------------------------------------------------------------------
# tracker_sql
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tracker_sql_create_insert_select(with_ctx: Path) -> None:
    ex = _executors()["tracker_sql"]

    r = await ex({"sql": "CREATE TABLE competitors (slug TEXT PRIMARY KEY, name TEXT)"})
    assert r["success"] is True and r["kind"] == "exec"

    r = await ex({"sql": "INSERT INTO competitors VALUES ('acme', 'Acme')"})
    assert r["success"] is True and r["rowcount"] == 1

    r = await ex({"sql": "SELECT slug, name FROM competitors"})
    assert r["success"] is True
    assert r["columns"] == ["slug", "name"]
    assert r["rows"] == [["acme", "Acme"]]


@pytest.mark.asyncio
async def test_tracker_sql_denylist_passthrough(with_ctx: Path) -> None:
    """Denylist errors must surface as success=False, not raise."""
    r = await _executors()["tracker_sql"]({"sql": "ATTACH DATABASE 'x' AS y"})
    assert r["success"] is False
    assert "denied" in r["error"].lower()


@pytest.mark.asyncio
async def test_tracker_sql_sqlite_error_surfaces(with_ctx: Path) -> None:
    """SQLite syntax errors are reported (not crashed)."""
    r = await _executors()["tracker_sql"]({"sql": "SELECT * FROM no_such_table"})
    assert r["success"] is False
    assert "sqlite" in r["error"].lower() or "no such table" in r["error"].lower()


@pytest.mark.asyncio
async def test_tracker_sql_empty_input(with_ctx: Path) -> None:
    r = await _executors()["tracker_sql"]({"sql": "  "})
    assert r["success"] is False


# ---------------------------------------------------------------------------
# tracker_register_writable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_happy_path_upsert(with_ctx: Path) -> None:
    sql = _executors()["tracker_sql"]
    reg = _executors()["tracker_register_writable"]

    await sql({"sql": ("CREATE TABLE competitors (  slug TEXT PRIMARY KEY,  name TEXT,  funding INTEGER)")})
    r = await reg(
        {
            "table": "competitors",
            "write_columns": ["name", "funding"],
            "key_columns": ["slug"],
        }
    )
    assert r["success"] is True
    assert r["mode"] == "upsert"

    # Verify the registry row landed.
    rows = await sql({"sql": "SELECT table_name, mode FROM _tracker_registry"})
    assert rows["rows"] == [["competitors", "upsert"]]


@pytest.mark.asyncio
async def test_register_rejects_missing_key_columns(with_ctx: Path) -> None:
    """Registration without key_columns is rejected so workers can't
    create duplicate rows on re-dispatch."""
    sql = _executors()["tracker_sql"]
    reg = _executors()["tracker_register_writable"]

    await sql({"sql": "CREATE TABLE events (msg TEXT, ts TEXT)"})
    r = await reg({"table": "events", "write_columns": ["msg", "ts"]})
    assert r["success"] is False
    assert "key_columns" in r["error"]

    r2 = await reg({"table": "events", "write_columns": ["msg", "ts"], "key_columns": []})
    assert r2["success"] is False
    assert "key_columns" in r2["error"]


@pytest.mark.asyncio
async def test_register_rejects_protected_table(with_ctx: Path) -> None:
    r = await _executors()["tracker_register_writable"]({"table": "_tracker_registry", "write_columns": ["table_name"]})
    assert r["success"] is False
    assert "protected" in r["error"].lower() or "_tracker_registry" in r["error"]


@pytest.mark.asyncio
async def test_register_rejects_missing_table(with_ctx: Path) -> None:
    r = await _executors()["tracker_register_writable"]({"table": "ghost", "write_columns": ["x"], "key_columns": ["x"]})
    assert r["success"] is False
    assert "does not exist" in r["error"]


@pytest.mark.asyncio
async def test_register_rejects_missing_columns(with_ctx: Path) -> None:
    sql = _executors()["tracker_sql"]
    await sql({"sql": "CREATE TABLE t (a INTEGER PRIMARY KEY, b TEXT)"})
    r = await _executors()["tracker_register_writable"]({"table": "t", "write_columns": ["b", "nonexistent"], "key_columns": ["a"]})
    assert r["success"] is False
    assert "nonexistent" in r["error"]


@pytest.mark.asyncio
async def test_register_rejects_upsert_without_unique_index(with_ctx: Path) -> None:
    sql = _executors()["tracker_sql"]
    # No PRIMARY KEY, no UNIQUE INDEX on slug — upsert can't work.
    await sql({"sql": "CREATE TABLE competitors (slug TEXT, name TEXT)"})
    r = await _executors()["tracker_register_writable"](
        {
            "table": "competitors",
            "write_columns": ["name"],
            "key_columns": ["slug"],
            "mode": "upsert",
        }
    )
    assert r["success"] is False
    assert "UNIQUE" in r["error"]


@pytest.mark.asyncio
async def test_register_accepts_unique_index_as_key(with_ctx: Path) -> None:
    sql = _executors()["tracker_sql"]
    await sql({"sql": "CREATE TABLE t (slug TEXT, name TEXT)"})
    await sql({"sql": "CREATE UNIQUE INDEX idx_t_slug ON t (slug)"})
    r = await _executors()["tracker_register_writable"]({"table": "t", "write_columns": ["name"], "key_columns": ["slug"]})
    assert r["success"] is True


@pytest.mark.asyncio
async def test_register_re_register_replaces_spec(with_ctx: Path) -> None:
    sql = _executors()["tracker_sql"]
    reg = _executors()["tracker_register_writable"]

    await sql({"sql": "CREATE TABLE t (a TEXT PRIMARY KEY, b TEXT, c TEXT)"})
    r1 = await reg({"table": "t", "write_columns": ["b"], "key_columns": ["a"]})
    assert r1["success"] is True
    r2 = await reg({"table": "t", "write_columns": ["b", "c"], "key_columns": ["a"]})
    assert r2["success"] is True

    rows = await sql({"sql": "SELECT write_columns FROM _tracker_registry WHERE table_name='t'"})
    stored = json.loads(rows["rows"][0][0])
    assert set(stored) == {"b", "c"}


# ---------------------------------------------------------------------------
# tracker_upsert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_inserts_then_updates(with_ctx: Path) -> None:
    sql = _executors()["tracker_sql"]
    reg = _executors()["tracker_register_writable"]
    up = _executors()["tracker_upsert"]

    await sql({"sql": ("CREATE TABLE competitors (  slug TEXT PRIMARY KEY,  name TEXT,  funding INTEGER)")})
    await reg(
        {
            "table": "competitors",
            "write_columns": ["name", "funding"],
            "key_columns": ["slug"],
        }
    )

    r1 = await up({"table": "competitors", "row": {"slug": "acme", "name": "Acme", "funding": 1000}})
    assert r1["success"] is True

    r2 = await up({"table": "competitors", "row": {"slug": "acme", "funding": 2000}})
    assert r2["success"] is True

    rows = await sql({"sql": "SELECT slug, name, funding FROM competitors"})
    # Name was preserved (not in the second upsert), funding updated.
    assert rows["rows"] == [["acme", "Acme", 2000]]


@pytest.mark.asyncio
async def test_upsert_rejects_unregistered_table(with_ctx: Path) -> None:
    sql = _executors()["tracker_sql"]
    up = _executors()["tracker_upsert"]
    await sql({"sql": "CREATE TABLE unregistered (x TEXT PRIMARY KEY)"})
    r = await up({"table": "unregistered", "row": {"x": "y"}})
    assert r["success"] is False
    assert "not registered" in r["error"]


@pytest.mark.asyncio
async def test_upsert_rejects_protected_namespace(with_ctx: Path) -> None:
    r = await _executors()["tracker_upsert"]({"table": "_tracker_registry", "row": {"table_name": "x"}})
    assert r["success"] is False
    assert "framework-owned" in r["error"]


@pytest.mark.asyncio
async def test_upsert_rejects_columns_outside_writelist(with_ctx: Path) -> None:
    sql = _executors()["tracker_sql"]
    reg = _executors()["tracker_register_writable"]
    up = _executors()["tracker_upsert"]

    await sql({"sql": ("CREATE TABLE t (a TEXT PRIMARY KEY, b TEXT, secret TEXT)")})
    await reg({"table": "t", "write_columns": ["b"], "key_columns": ["a"]})

    r = await up({"table": "t", "row": {"a": "k", "b": "ok", "secret": "leak"}})
    assert r["success"] is False
    assert "secret" in r["error"]


@pytest.mark.asyncio
async def test_upsert_requires_key_columns_in_upsert_mode(with_ctx: Path) -> None:
    sql = _executors()["tracker_sql"]
    reg = _executors()["tracker_register_writable"]
    up = _executors()["tracker_upsert"]

    await sql({"sql": "CREATE TABLE t (a TEXT PRIMARY KEY, b TEXT)"})
    await reg({"table": "t", "write_columns": ["b"], "key_columns": ["a"]})

    r = await up({"table": "t", "row": {"b": "no key here"}})
    assert r["success"] is False
    assert "key_columns" in r["error"]


@pytest.mark.asyncio
async def test_upsert_encodes_complex_values_as_json(with_ctx: Path) -> None:
    sql = _executors()["tracker_sql"]
    reg = _executors()["tracker_register_writable"]
    up = _executors()["tracker_upsert"]

    await sql({"sql": "CREATE TABLE t (slug TEXT PRIMARY KEY, sources TEXT)"})
    await reg({"table": "t", "write_columns": ["sources"], "key_columns": ["slug"]})

    await up(
        {
            "table": "t",
            "row": {"slug": "acme", "sources": ["a.com", "b.com"]},
        }
    )
    rows = await sql({"sql": "SELECT sources FROM t WHERE slug='acme'"})
    assert json.loads(rows["rows"][0][0]) == ["a.com", "b.com"]


# ---------------------------------------------------------------------------
# Registration helpers
# ---------------------------------------------------------------------------


def test_queen_only_tracker_tools_set() -> None:
    """The constant must reflect the design: tracker_sql and
    tracker_register_writable are queen-only; tracker_upsert is shared."""
    assert "tracker_sql" in QUEEN_ONLY_TRACKER_TOOLS
    assert "tracker_register_writable" in QUEEN_ONLY_TRACKER_TOOLS
    assert "tracker_upsert" not in QUEEN_ONLY_TRACKER_TOOLS


def test_register_tracker_tools_full_set() -> None:
    reg = ToolRegistry()
    register_tracker_tools(reg)
    names = set(reg.get_tools().keys())
    assert {
        "tracker_sql",
        "tracker_register_writable",
        "tracker_upsert",
        "tracker_query",
    }.issubset(names)


def test_register_tracker_tools_worker_role_skips_queen_only() -> None:
    """role='worker' must register tracker_upsert + tracker_query, not the queen-only pair."""
    reg = ToolRegistry()
    register_tracker_tools(reg, role="worker")
    names = set(reg.get_tools().keys())
    assert "tracker_upsert" in names
    assert "tracker_query" in names  # workers read assignment context
    assert "tracker_sql" not in names
    assert "tracker_register_writable" not in names


# ---------------------------------------------------------------------------
# tracker_query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tracker_query_select_works(with_ctx: Path) -> None:
    sql_ex = _executors()["tracker_sql"]
    q_ex = _executors()["tracker_query"]

    await sql_ex({"sql": "CREATE TABLE t (a INTEGER PRIMARY KEY, b TEXT)"})
    await sql_ex({"sql": "INSERT INTO t VALUES (1, 'x'), (2, 'y')"})

    r = await q_ex({"sql": "SELECT a, b FROM t ORDER BY a"})
    assert r["success"] is True
    assert r["kind"] == "rows"
    assert r["columns"] == ["a", "b"]
    assert r["rows"] == [[1, "x"], [2, "y"]]


@pytest.mark.asyncio
async def test_tracker_query_with_cte_allowed(with_ctx: Path) -> None:
    sql_ex = _executors()["tracker_sql"]
    q_ex = _executors()["tracker_query"]
    await sql_ex({"sql": "CREATE TABLE t (a INTEGER)"})
    await sql_ex({"sql": "INSERT INTO t VALUES (1), (2), (3)"})

    r = await q_ex({"sql": "WITH big AS (SELECT a FROM t WHERE a > 1) SELECT * FROM big"})
    assert r["success"] is True
    assert r["rows"] == [[2], [3]]


@pytest.mark.asyncio
async def test_tracker_query_can_introspect_registry(with_ctx: Path) -> None:
    """Workers can SELECT from _tracker_registry to learn their schema."""
    sql_ex = _executors()["tracker_sql"]
    reg_ex = _executors()["tracker_register_writable"]
    q_ex = _executors()["tracker_query"]

    await sql_ex({"sql": "CREATE TABLE c (k TEXT PRIMARY KEY, v TEXT)"})
    await reg_ex({"table": "c", "write_columns": ["v"], "key_columns": ["k"]})
    r = await q_ex({"sql": "SELECT table_name, mode FROM _tracker_registry"})
    assert r["success"] is True
    assert r["rows"] == [["c", "upsert"]]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_sql",
    [
        "INSERT INTO t VALUES (1)",
        "UPDATE t SET a=2",
        "DELETE FROM t",
        "CREATE TABLE x (a INT)",
        "DROP TABLE t",
        "ALTER TABLE t ADD COLUMN c TEXT",
        "REPLACE INTO t VALUES (1)",
        # WITH-prefixed DML must resolve to its write verb — a leading
        # WITH is not proof of a read (SQLite allows WITH ... DELETE).
        "WITH x AS (SELECT 1) DELETE FROM t",
        "WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x",
        "WITH x AS (SELECT 1) UPDATE t SET a=3",
        # A leading comment must not mask the verb.
        "/* read-ish */ DELETE FROM t",
    ],
)
async def test_tracker_query_rejects_writes(with_ctx: Path, bad_sql: str) -> None:
    r = await _executors()["tracker_query"]({"sql": bad_sql})
    assert r["success"] is False
    # Either the SELECT-only check or the underlying denylist fires; both
    # are acceptable, both should reject.
    err = r["error"].lower()
    assert "select-only" in err or "denied" in err or "rejected" in err


@pytest.mark.asyncio
async def test_tracker_query_rejects_multi_statement(with_ctx: Path) -> None:
    r = await _executors()["tracker_query"]({"sql": "SELECT 1; SELECT 2"})
    assert r["success"] is False
    assert "ONE statement" in r["error"]


@pytest.mark.asyncio
async def test_tracker_query_denylist_still_applies(with_ctx: Path) -> None:
    """Even though the leading kw is SELECT, ATTACH must be rejected."""
    # ATTACH is at start so leading-keyword check catches it first.
    r = await _executors()["tracker_query"]({"sql": "ATTACH DATABASE 'x' AS y"})
    assert r["success"] is False


@pytest.mark.asyncio
async def test_tracker_query_no_colony_context() -> None:
    token = _execution_context.set({})
    try:
        r = await _executors()["tracker_query"]({"sql": "SELECT 1"})
        assert r["success"] is False
        assert "no colony" in r["error"]
    finally:
        _execution_context.reset(token)


def test_register_tracker_tools_invalid_role() -> None:
    reg = ToolRegistry()
    with pytest.raises(ValueError, match="role"):
        register_tracker_tools(reg, role="bogus")


# ---------------------------------------------------------------------------
# change log (_tracker_changes)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_log_records_worker_upserts(with_ctx: Path) -> None:
    """Registration installs row-level triggers; each worker write lands in
    _tracker_changes with the row's pk, so the UI can show WHICH rows
    changed — an update to an existing row is invisible to row counts."""
    ex = _executors()
    await ex["tracker_sql"]({"sql": "CREATE TABLE c (k TEXT PRIMARY KEY, v TEXT)"})
    await ex["tracker_register_writable"]({"table": "c", "write_columns": ["v"], "key_columns": ["k"]})

    await ex["tracker_upsert"]({"table": "c", "row": {"k": "a", "v": "1"}})
    await ex["tracker_upsert"]({"table": "c", "row": {"k": "a", "v": "2"}})  # same key → update path

    r = await ex["tracker_query"]({"sql": "SELECT table_name, pk, op FROM _tracker_changes ORDER BY id"})
    assert r["success"] is True
    assert r["rows"] == [
        ["c", '{"k":"a"}', "insert"],
        ["c", '{"k":"a"}', "update"],
    ]


@pytest.mark.asyncio
async def test_change_log_records_queen_raw_sql(with_ctx: Path) -> None:
    """Triggers live in the DB file, so writes that bypass tracker_upsert
    (the queen's raw SQL) are logged too — no writer cooperation needed."""
    ex = _executors()
    await ex["tracker_sql"]({"sql": "CREATE TABLE c (k TEXT PRIMARY KEY, v TEXT)"})
    await ex["tracker_register_writable"]({"table": "c", "write_columns": ["v"], "key_columns": ["k"]})

    await ex["tracker_sql"]({"sql": "INSERT INTO c VALUES ('x', '1'); UPDATE c SET v = '2' WHERE k = 'x'"})

    r = await ex["tracker_query"]({"sql": "SELECT pk, op FROM _tracker_changes ORDER BY id"})
    assert r["rows"] == [['{"k":"x"}', "insert"], ['{"k":"x"}', "update"]]


@pytest.mark.asyncio
async def test_change_log_triggers_survive_queen_drop_attempt(with_ctx: Path) -> None:
    """The queen must not be able to disable change tracking: trigger names
    are in the protected '_' namespace, so DROP TRIGGER is denied and
    writes keep logging afterwards."""
    ex = _executors()
    await ex["tracker_sql"]({"sql": "CREATE TABLE c (k TEXT PRIMARY KEY, v TEXT)"})
    await ex["tracker_register_writable"]({"table": "c", "write_columns": ["v"], "key_columns": ["k"]})

    r = await ex["tracker_sql"]({"sql": "DROP TRIGGER _tracker_chg__c__ins"})
    assert r["success"] is False

    await ex["tracker_upsert"]({"table": "c", "row": {"k": "a", "v": "1"}})
    r = await ex["tracker_query"]({"sql": "SELECT COUNT(*) FROM _tracker_changes"})
    assert r["rows"] == [[1]]


@pytest.mark.asyncio
async def test_change_log_unregistered_table_not_logged(with_ctx: Path) -> None:
    """Unregistered (queen-scratch) tables have no triggers — writes there
    stay out of the change log; the UI falls back to row-count diffing."""
    ex = _executors()
    await ex["tracker_sql"]({"sql": "CREATE TABLE scratch (a INTEGER)"})
    await ex["tracker_sql"]({"sql": "INSERT INTO scratch VALUES (1)"})
    r = await ex["tracker_query"]({"sql": "SELECT COUNT(*) FROM _tracker_changes"})
    assert r["rows"] == [[0]]
