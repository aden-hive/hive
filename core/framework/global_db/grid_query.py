"""Safe SQL construction for the global-DB grid endpoints.

The cloud global-DB backend offers structured REST for *list / update* but no
filtering, free-text search, insert or delete. It does expose a raw-SQL escape
hatch (``/v1/global-db/sql`` and ``/query``) that runs under a per-team
NOSUPERUSER role with a statement timeout and a keyword denylist. Rather than
grow a filter DSL in the cloud service, the desktop proxy composes those
raw-SQL endpoints to give the grid its "power" features.

Because ``query``/``sql`` take SQL *text* (the client has no bound-parameter
channel), **every identifier and literal interpolated into a generated
statement must be validated/escaped here**. This module is the single trust
boundary for that. Keep all string interpolation in this file and unit-test it
hard — see ``tests/test_grid_query.py``.

Identifiers are restricted to ``[A-Za-z_][A-Za-z0-9_]*`` (the shape of every
column in this schema), which sidesteps quoting edge cases entirely: anything
outside that set is rejected, not escaped. Literals are rendered for Postgres
with ``standard_conforming_strings`` on (the default), where the only special
character inside a single-quoted string is the quote itself.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# op name -> SQL operator for scalar comparisons.
_COMPARISON = {
    "eq": "=",
    "ne": "<>",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
}
# ILIKE-based ops -> (prefix, suffix) wrapped around the escaped value.
_LIKE = {
    "contains": ("%", "%"),
    "starts_with": ("", "%"),
    "ends_with": ("%", ""),
}
# Ops that ignore any provided value.
_NULLARY = {"is_empty", "is_not_empty"}


class SqlBuildError(ValueError):
    """A filter/search/identifier failed validation. Surfaced as HTTP 400."""


def quote_ident(name: str, allowed: set[str] | None = None) -> str:
    """Validate and double-quote a column/table identifier.

    ``allowed`` (when given) is the set of real column names for the table;
    an identifier outside it is rejected rather than passed to the DB, so a
    crafted filter can't probe other columns/tables.
    """
    if not isinstance(name, str) or not _IDENT_RE.match(name):
        raise SqlBuildError(f"invalid identifier: {name!r}")
    if allowed is not None and name not in allowed:
        raise SqlBuildError(f"unknown column: {name}")
    return f'"{name}"'


def sql_literal(value: Any) -> str:
    """Render a JSON scalar as a Postgres literal. Rejects non-finite floats."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):  # bool is a subclass of int — check first
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise SqlBuildError("non-finite numeric literal")
        return repr(value)
    # Treat everything else as text. NUL bytes can't be stored in a pg text
    # column and would corrupt the statement; drop them.
    s = str(value).replace("\x00", "")
    return "'" + s.replace("'", "''") + "'"


def _like_escape(value: Any) -> str:
    """Escape LIKE metacharacters so a user's value matches literally."""
    s = str(value).replace("\x00", "")
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _as_text(ident: str) -> str:
    """Cast an identifier to text so ILIKE works on non-text columns too."""
    return f"CAST({ident} AS TEXT)"


def _condition(f: dict[str, Any], allowed: set[str]) -> str:
    if not isinstance(f, dict):
        raise SqlBuildError("each filter must be an object")
    col = f.get("column")
    op = f.get("op", "eq")
    ident = quote_ident(col, allowed)

    if op in _NULLARY:
        if op == "is_empty":
            return f"({ident} IS NULL OR {_as_text(ident)} = '')"
        return f"({ident} IS NOT NULL AND {_as_text(ident)} <> '')"

    if op in _COMPARISON:
        return f"{ident} {_COMPARISON[op]} {sql_literal(f.get('value'))}"

    if op in _LIKE:
        prefix, suffix = _LIKE[op]
        pattern = prefix + _like_escape(f.get("value")) + suffix
        return f"{_as_text(ident)} ILIKE {sql_literal(pattern)} ESCAPE '\\'"

    raise SqlBuildError(f"unsupported filter op: {op!r}")


def build_filter_clause(filters: Iterable[dict[str, Any]] | None, allowed: set[str]) -> str:
    """AND-joined boolean expression for a list of filters (no WHERE prefix)."""
    if not filters:
        return ""
    parts = [_condition(f, allowed) for f in filters]
    return " AND ".join(p for p in parts if p)


def build_search_clause(search: Any, allowed: set[str]) -> str:
    """OR-joined ``CAST(col AS TEXT) ILIKE '%term%'`` across every column."""
    if search is None or str(search).strip() == "":
        return ""
    pattern = "%" + _like_escape(search) + "%"
    lit = sql_literal(pattern)
    cols = sorted(allowed)
    if not cols:
        return ""
    ors = " OR ".join(f"{_as_text(quote_ident(c))} ILIKE {lit} ESCAPE '\\'" for c in cols)
    return f"({ors})"


def _combine_where(*clauses: str) -> str:
    active = [c for c in clauses if c]
    if not active:
        return ""
    return " WHERE " + " AND ".join(active)


def build_select(
    table: str,
    allowed: set[str],
    *,
    filters: Iterable[dict[str, Any]] | None = None,
    search: Any = None,
    order_by: str | None = None,
    order_dir: str = "asc",
    limit: int = 100,
    offset: int = 0,
) -> str:
    t = quote_ident(table)
    where = _combine_where(
        build_filter_clause(filters, allowed),
        build_search_clause(search, allowed),
    )
    sql = f"SELECT * FROM {t}{where}"
    if order_by:
        direction = "DESC" if str(order_dir).lower() == "desc" else "ASC"
        sql += f" ORDER BY {quote_ident(order_by, allowed)} {direction}"
    sql += f" LIMIT {int(limit)} OFFSET {int(offset)}"
    return sql


def build_count(
    table: str,
    allowed: set[str],
    *,
    filters: Iterable[dict[str, Any]] | None = None,
    search: Any = None,
) -> str:
    t = quote_ident(table)
    where = _combine_where(
        build_filter_clause(filters, allowed),
        build_search_clause(search, allowed),
    )
    return f"SELECT count(*) AS total FROM {t}{where}"


def build_group_counts(
    table: str,
    allowed: set[str],
    *,
    group_by: str,
    filters: Iterable[dict[str, Any]] | None = None,
    search: Any = None,
    limit: int | None = None,
) -> str:
    """One row per distinct ``group_by`` value with its total count under the
    active filters/search — ``SELECT col AS value, count(*) AS count ... GROUP
    BY col ORDER BY count DESC``. Lets board/grouped views size and order their
    columns with a single query instead of loading every row. ``limit`` caps the
    number of distinct groups returned (highest-count first)."""
    t = quote_ident(table)
    col = quote_ident(group_by, allowed)
    where = _combine_where(
        build_filter_clause(filters, allowed),
        build_search_clause(search, allowed),
    )
    sql = f"SELECT {col} AS value, count(*) AS count FROM {t}{where} GROUP BY {col} ORDER BY count(*) DESC, {col} ASC"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"
    return sql


def build_delete(table: str, pk: dict[str, Any], pk_cols: list[str]) -> str:
    if not pk_cols:
        raise SqlBuildError("table has no primary key")
    conds = " AND ".join(f"{quote_ident(c)} = {sql_literal(pk[c])}" for c in pk_cols)
    return f"DELETE FROM {quote_ident(table)} WHERE {conds}"
