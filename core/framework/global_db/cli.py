"""``hive-global-db`` — CLI for the shared cloud team global DB.

For agent use via ``terminal_exec`` when bulk / large-data operations are
awkward as individual tracker tool calls (CSV import/export, big ad-hoc
queries). Reads ``HIVE_CLOUD_JWT`` / ``HIVE_CLOUD_BASE`` from the env (set by
the desktop shell) and talks to hive-backend ``/v1/global-db/*``.

Run: ``python -m framework.global_db.cli <command> ...``

Commands:
  tables                                  list tables + row counts
  query "<SELECT …>" [--row-cap N]        read-only SQL
  sql "<SQL>" [--row-cap N]               full SQL (DDL/DML/SELECT)
  upsert --table T --row '<json>'         upsert one row
  import --table T --file rows.csv|.json  bulk upsert (batched)
  export --table T [--format csv|json]    stream a whole table out
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from typing import Any

from framework.global_db import client as gdb

_IMPORT_BATCH = 1000
_EXPORT_PAGE = 500


def _run(coro: Any) -> Any:
    try:
        return asyncio.run(coro)
    except gdb.NotSignedInError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)
    except gdb.GlobalDbError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


def _dump(obj: Any) -> None:
    print(json.dumps(obj, indent=2, default=str))


def cmd_tables(args: argparse.Namespace) -> None:
    _dump(_run(gdb.list_tables()))


def cmd_query(args: argparse.Namespace) -> None:
    _dump(_run(gdb.query(args.sql, row_cap=args.row_cap)))


def cmd_sql(args: argparse.Namespace) -> None:
    _dump(_run(gdb.sql(args.sql, row_cap=args.row_cap)))


def cmd_upsert(args: argparse.Namespace) -> None:
    try:
        row = json.loads(args.row)
    except json.JSONDecodeError as e:
        print(f"error: --row is not valid JSON: {e}", file=sys.stderr)
        sys.exit(1)
    _dump(_run(gdb.upsert(args.table, row, source_colony=args.source_colony)))


def _read_rows(path: str) -> list[dict[str, Any]]:
    if path.endswith(".json"):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise ValueError("JSON import file must be an array of row objects")
        return data
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def cmd_import(args: argparse.Namespace) -> None:
    rows = _read_rows(args.file)
    total = 0
    for i in range(0, len(rows), _IMPORT_BATCH):
        chunk = rows[i : i + _IMPORT_BATCH]
        res = _run(gdb.import_rows(args.table, chunk, source_colony=args.source_colony))
        total += int(res.get("count", len(chunk)))
        print(f"imported {total}/{len(rows)}", file=sys.stderr)
    _dump({"success": True, "count": total})


def cmd_export(args: argparse.Namespace) -> None:
    offset = 0
    columns: list[str] | None = None
    all_rows: list[dict[str, Any]] = []
    while True:
        res = _run(gdb.list_rows(args.table, params={"limit": _EXPORT_PAGE, "offset": offset}))
        rows = res.get("rows", [])
        if columns is None:
            columns = [c["name"] for c in res.get("columns", [])]
        all_rows.extend(rows)
        if len(rows) < _EXPORT_PAGE:
            break
        offset += _EXPORT_PAGE
    columns = columns or []
    if args.format == "csv":
        writer = csv.DictWriter(sys.stdout, fieldnames=columns)
        writer.writeheader()
        for r in all_rows:
            writer.writerow({c: r.get(c) for c in columns})
    else:
        _dump(all_rows)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="hive-global-db", description="Shared cloud team global DB CLI.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("tables", help="list tables + row counts")
    sp.set_defaults(func=cmd_tables)

    sp = sub.add_parser("query", help="read-only SQL")
    sp.add_argument("sql")
    sp.add_argument("--row-cap", type=int, default=None)
    sp.set_defaults(func=cmd_query)

    sp = sub.add_parser("sql", help="full SQL (DDL/DML/SELECT)")
    sp.add_argument("sql")
    sp.add_argument("--row-cap", type=int, default=None)
    sp.set_defaults(func=cmd_sql)

    sp = sub.add_parser("upsert", help="upsert one row")
    sp.add_argument("--table", required=True)
    sp.add_argument("--row", required=True, help="JSON object of column->value")
    sp.add_argument("--source-colony", default=None)
    sp.set_defaults(func=cmd_upsert)

    sp = sub.add_parser("import", help="bulk upsert from CSV/JSON")
    sp.add_argument("--table", required=True)
    sp.add_argument("--file", required=True, help="CSV or JSON (array) file")
    sp.add_argument("--source-colony", default=None)
    sp.set_defaults(func=cmd_import)

    sp = sub.add_parser("export", help="stream a whole table out")
    sp.add_argument("--table", required=True)
    sp.add_argument("--format", choices=["csv", "json"], default="csv")
    sp.set_defaults(func=cmd_export)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
