import { api } from "./client";

/** A SQLite cell value, constrained to JSON-serialisable types that
 *  Python maps into sqlite3 param placeholders without surprises. */
export type CellValue = string | number | boolean | null;

export interface ColumnInfo {
  name: string;
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

export interface UpdateRowRequest {
  /** Primary key column(s) → value(s). All PK columns must be present. */
  pk: Record<string, CellValue>;
  /** Column(s) → new value(s). Cannot include PK columns. */
  updates: Record<string, CellValue>;
}

export const colonyDataApi = {
  /** List user tables in the colony's progress.db with row counts. */
  listTables: (sessionId: string) =>
    api.get<{ tables: TableOverview[] }>(
      `/sessions/${sessionId}/colony/data/tables`,
    ),

  /** Paginated rows for a table. Server enforces limit ≤ 500. */
  listRows: (
    sessionId: string,
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
      `/sessions/${sessionId}/colony/data/tables/${encodeURIComponent(table)}/rows${qs ? `?${qs}` : ""}`,
    );
  },

  /** Update a single row by primary key. Returns {updated: 0|1}. */
  updateRow: (sessionId: string, table: string, body: UpdateRowRequest) =>
    api.patch<{ updated: number }>(
      `/sessions/${sessionId}/colony/data/tables/${encodeURIComponent(table)}/rows`,
      body,
    ),
};
