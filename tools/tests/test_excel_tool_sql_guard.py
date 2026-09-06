"""excel_sql query guard: word-boundary matching of write/DDL keywords."""

from __future__ import annotations

import pytest


def test_select_with_keyword_inside_column_names_is_allowed():
    """A column whose name contains a keyword is not a write.

    `created_at` contains CREATE and `updated_at` contains UPDATE. The guard
    used a bare substring test, so these ordinary SELECTs never ran.
    """
    from aden_tools.tools.excel_tool.excel_tool import _validate_select_query

    assert _validate_select_query("SELECT created_at, updated_at FROM data") is None


@pytest.mark.parametrize(
    "query",
    [
        "SELECT created_at FROM data",
        "SELECT updated_at FROM data",
        "SELECT * FROM data WHERE status = 'DELETED'",
        "SELECT total AS total_created FROM data",
        "SELECT deleted_flag, dropped_count FROM data",
        "SELECT alteration, execution_time FROM data",
        "SELECT truncated_name FROM data",
        "  SELECT a FROM data",
        "select lower_case_keyword FROM data",
    ],
)
def test_read_only_selects_are_allowed(query):
    from aden_tools.tools.excel_tool.excel_tool import _validate_select_query

    assert _validate_select_query(query) is None, query


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("SELECT * FROM data; DROP TABLE data", "'DROP'"),
        ("SELECT * FROM data UNION SELECT 1; DELETE FROM data", "'DELETE'"),
        ("SELECT * FROM (INSERT INTO x VALUES (1))", "'INSERT'"),
        ("SELECT * FROM data WHERE 1=1 alter table x", "'ALTER'"),
        ("SELECT exec(1)", "'EXEC'"),
        ("SELECT truncate(x) FROM data", "'TRUNCATE'"),
    ],
)
def test_write_keywords_are_still_blocked(query, expected):
    """Relaxing to word boundaries must not let a real write through."""
    from aden_tools.tools.excel_tool.excel_tool import _validate_select_query

    error = _validate_select_query(query)
    assert error is not None, query
    assert expected in error, error


@pytest.mark.parametrize(
    "query",
    ["DROP TABLE data", "UPDATE data SET a = 1", "INSERT INTO data VALUES (1)"],
)
def test_non_select_statements_are_rejected(query):
    from aden_tools.tools.excel_tool.excel_tool import _validate_select_query

    error = _validate_select_query(query)
    assert error is not None
    assert "Only SELECT queries are allowed" in error


@pytest.mark.parametrize("query", ["", "   ", "\n\t "])
def test_empty_query_is_rejected(query):
    from aden_tools.tools.excel_tool.excel_tool import _validate_select_query

    assert _validate_select_query(query) == "query cannot be empty"
