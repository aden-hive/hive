import { api } from "./client";

/** A SQLite cell value, constrained to JSON-serialisable types that
 *  Python maps into sqlite3 param placeholders without surprises. */
export type CellValue = string | number | boolean | null;

export interface ColumnInfo {
  name: string;
  /** Human label, when the source has one (the CRM projection supplies it).
   *  Raw SQLite tables don't, so anything rendering it falls back to `name`. */
  label?: string;
  /** SQLite declared type (e.g. "TEXT", "INTEGER"). May be empty string. */
  type: string;
  notnull: boolean;
  /** >0 means part of the primary key (ordinal position). 0 = not PK. */
  pk: number;
  dflt_value: string | null;
}

export interface TableOverview {
  name: string;
  columns: ColumnInfo[];
  row_count: number;
  primary_key: string[];
}

export interface TableRowsResponse {
  table: string;
  columns: ColumnInfo[];
  primary_key: string[];
  rows: Record<string, CellValue>[];
  total: number;
  limit: number;
  offset: number;
}

export interface ChangedRow {
  /** Key column(s) → value(s) identifying the changed row. */
  pk: Record<string, CellValue>;
  op: "insert" | "update";
}

export interface TableChanges {
  /** Distinct rows changed in the window. */
  count: number;
  rows: ChangedRow[];
}

export interface ChangesResponse {
  /** Max change-log id; pass back as `since` on the next poll. */
  cursor: number;
  /** Tables with change triggers installed (i.e. registered tables).
   *  Tables absent here have no row-level log — fall back to counts. */
  covered: string[];
  truncated: boolean;
  tables: Record<string, TableChanges>;
}

export interface UpdateRowRequest {
  /** Primary key column(s) → value(s). All PK columns must be present. */
  pk: Record<string, CellValue>;
  /** Column(s) → new value(s). Cannot include PK columns. */
  updates: Record<string, CellValue>;
}

export const colonyDataApi = {
  /** List user tables in the colony's tracker.db with row counts.
   *
   *  Routed by colony directory name (not session) because tracker.db
   *  is per-colony — one DB serves every session for that colony, and
   *  the data is reachable even when no session is live. */
  listTables: (colonyName: string) =>
    api.get<{ tables: TableOverview[] }>(
      `/colonies/${encodeURIComponent(colonyName)}/data/tables`,
    ),

  /** Paginated rows for a table. Server enforces limit ≤ 500. */
  listRows: (
    colonyName: string,
    table: string,
    opts: {
      limit?: number;
      offset?: number;
      orderBy?: string | null;
      orderDir?: "asc" | "desc";
    } = {},
  ) => {
    const params = new URLSearchParams();
    if (opts.limit != null) params.set("limit", String(opts.limit));
    if (opts.offset != null) params.set("offset", String(opts.offset));
    if (opts.orderBy) params.set("order_by", opts.orderBy);
    if (opts.orderDir) params.set("order_dir", opts.orderDir);
    const qs = params.toString();
    return api.get<TableRowsResponse>(
      `/colonies/${encodeURIComponent(colonyName)}/data/tables/${encodeURIComponent(table)}/rows${qs ? `?${qs}` : ""}`,
    );
  },

  /** Row-level changes since a change-log cursor. `since = -1` is the
   *  init call: returns only the current cursor + trigger coverage so
   *  the first poll doesn't report history as new. */
  listChanges: (colonyName: string, since: number) =>
    api.get<ChangesResponse>(
      `/colonies/${encodeURIComponent(colonyName)}/data/changes?since=${since}`,
    ),

  /** Update a single row by primary key. Returns {updated: 0|1}. */
  updateRow: (colonyName: string, table: string, body: UpdateRowRequest) =>
    api.patch<{ updated: number }>(
      `/colonies/${encodeURIComponent(colonyName)}/data/tables/${encodeURIComponent(table)}/rows`,
      body,
    ),
};
