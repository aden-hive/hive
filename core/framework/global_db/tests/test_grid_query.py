"""Unit tests for ``grid_query`` — the SQL-injection trust boundary.

These assert WHY the generated SQL is safe: identifiers outside the schema's
allow-set are rejected (not escaped through), and user-supplied literals can't
break out of their quoting. A regression here is a security hole, not a
cosmetic bug, so the tests encode the threat model, not just happy paths.
"""

import pytest

from framework.global_db import grid_query as gq

COLS = {"name", "status", "amount", "email"}


# --- identifier validation -------------------------------------------------


def test_quote_ident_allows_known_column():
    assert gq.quote_ident("status", COLS) == '"status"'


@pytest.mark.parametrize(
    "bad",
    [
        "status; DROP TABLE leads",  # statement injection
        'name"',  # embedded quote
        "amount OR 1=1",  # space / boolean smuggle
        "",  # empty
        "1col",  # leading digit
        "col-name",  # hyphen
    ],
)
def test_quote_ident_rejects_malicious(bad):
    with pytest.raises(gq.SqlBuildError):
        gq.quote_ident(bad)


def test_quote_ident_rejects_unknown_column():
    # Syntactically valid but not a real column — must not reach the DB.
    with pytest.raises(gq.SqlBuildError):
        gq.quote_ident("secret_col", COLS)


# --- literal escaping ------------------------------------------------------


def test_sql_literal_escapes_quote_breakout():
    # The classic break-out attempt stays inside the string literal.
    assert gq.sql_literal("a' OR '1'='1") == "'a'' OR ''1''=''1'"


def test_sql_literal_types():
    assert gq.sql_literal(None) == "NULL"
    assert gq.sql_literal(True) == "TRUE"
    assert gq.sql_literal(False) == "FALSE"
    assert gq.sql_literal(42) == "42"
    assert gq.sql_literal(3.5) == "3.5"


def test_sql_literal_rejects_non_finite():
    with pytest.raises(gq.SqlBuildError):
        gq.sql_literal(float("inf"))
    with pytest.raises(gq.SqlBuildError):
        gq.sql_literal(float("nan"))


# --- filter conditions -----------------------------------------------------


def test_comparison_filter():
    clause = gq.build_filter_clause([{"column": "amount", "op": "gte", "value": 100}], COLS)
    assert clause == '"amount" >= 100'


def test_contains_filter_escapes_like_metachars():
    clause = gq.build_filter_clause([{"column": "name", "op": "contains", "value": "50%_off"}], COLS)
    # % and _ are escaped so they match literally, with ESCAPE declared.
    assert clause == "CAST(\"name\" AS TEXT) ILIKE '%50\\%\\_off%' ESCAPE '\\'"


def test_is_empty_filter():
    clause = gq.build_filter_clause([{"column": "email", "op": "is_empty"}], COLS)
    assert clause == '("email" IS NULL OR CAST("email" AS TEXT) = \'\')'


def test_unknown_op_rejected():
    with pytest.raises(gq.SqlBuildError):
        gq.build_filter_clause([{"column": "name", "op": "haxx", "value": 1}], COLS)


def test_filter_on_unknown_column_rejected():
    with pytest.raises(gq.SqlBuildError):
        gq.build_filter_clause([{"column": "evil", "op": "eq", "value": 1}], COLS)


def test_multiple_filters_anded():
    clause = gq.build_filter_clause(
        [
            {"column": "status", "op": "eq", "value": "won"},
            {"column": "amount", "op": "gt", "value": 0},
        ],
        COLS,
    )
    assert clause == '"status" = \'won\' AND "amount" > 0'


# --- search ----------------------------------------------------------------


def test_search_spans_all_columns():
    clause = gq.build_search_clause("acme", COLS)
    # One ILIKE per column, OR-joined, columns sorted for determinism.
    for c in COLS:
        assert f'CAST("{c}" AS TEXT) ILIKE' in clause
    assert clause.startswith("(") and clause.endswith(")")
    assert " OR " in clause


def test_blank_search_is_empty():
    assert gq.build_search_clause("   ", COLS) == ""
    assert gq.build_search_clause(None, COLS) == ""


# --- full statements -------------------------------------------------------


def test_build_select_full():
    sql = gq.build_select(
        "leads",
        COLS,
        filters=[{"column": "status", "op": "eq", "value": "new"}],
        order_by="amount",
        order_dir="desc",
        limit=50,
        offset=100,
    )
    assert sql == ('SELECT * FROM "leads" WHERE "status" = \'new\' ORDER BY "amount" DESC LIMIT 50 OFFSET 100')


def test_build_select_no_filters():
    sql = gq.build_select("leads", COLS, limit=10, offset=0)
    assert sql == 'SELECT * FROM "leads" LIMIT 10 OFFSET 0'


def test_build_select_clamps_order_dir_to_known_keyword():
    # An attacker-supplied order_dir can only ever become ASC or DESC.
    sql = gq.build_select("leads", COLS, order_by="name", order_dir="; DROP")
    assert sql.endswith('ORDER BY "name" ASC LIMIT 100 OFFSET 0')


def test_build_count_with_search():
    sql = gq.build_count("leads", COLS, search="x")
    assert sql.startswith('SELECT count(*) AS total FROM "leads" WHERE (')


def test_build_group_counts_basic():
    sql = gq.build_group_counts("leads", COLS, group_by="status")
    assert sql == ('SELECT "status" AS value, count(*) AS count FROM "leads" GROUP BY "status" ORDER BY count(*) DESC, "status" ASC')


def test_build_group_counts_with_filters_and_limit():
    sql = gq.build_group_counts(
        "leads",
        COLS,
        group_by="status",
        filters=[{"column": "email", "op": "contains", "value": "rick"}],
        limit=200,
    )
    assert sql.startswith('SELECT "status" AS value, count(*) AS count FROM "leads" WHERE ')
    assert 'CAST("email" AS TEXT) ILIKE' in sql  # the filter reached the WHERE
    assert sql.endswith('GROUP BY "status" ORDER BY count(*) DESC, "status" ASC LIMIT 200')


def test_build_group_counts_rejects_unknown_column():
    # The group column is user-chosen, so it must be allow-listed like any
    # other identifier — a bogus column can't reach the DB.
    with pytest.raises(gq.SqlBuildError):
        gq.build_group_counts("leads", COLS, group_by="status; DROP TABLE leads")


def test_build_delete():
    sql = gq.build_delete("leads", {"lead_id": "abc'123"}, ["lead_id"])
    assert sql == "DELETE FROM \"leads\" WHERE \"lead_id\" = 'abc''123'"


def test_build_delete_composite_pk():
    sql = gq.build_delete("m2m", {"a": 1, "b": 2}, ["a", "b"])
    assert sql == 'DELETE FROM "m2m" WHERE "a" = 1 AND "b" = 2'
