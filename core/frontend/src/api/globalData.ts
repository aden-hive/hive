import { api } from "./client";
import type {
  CellValue,
  ChangedRow,
  TableOverview,
  TableRowsResponse,
  UpdateRowRequest,
} from "./colonyData";

/** Row-level change feed over the team DB (cursor = max updated_at, stamped
 *  by server-side touch triggers). Same shape family as the per-colony
 *  tracker's /data/changes, plus a string cursor instead of an integer. */
export interface GlobalChangesResponse {
  /** Pass back verbatim as `since` on the next poll. Null = no rows yet. */
  cursor: string | null;
  /** Tables that participate in the feed (have updated_at + a pk). */
  covered: string[];
  truncated: boolean;
  tables: Record<string, { count: number; rows: ChangedRow[] }>;
}

/** Comparison operators understood by the global-DB query endpoint.
 *  Mirrors ``grid_query`` on the runtime — keep the two in sync. */
export type FilterOp =
  | "eq"
  | "ne"
  | "gt"
  | "gte"
  | "lt"
  | "lte"
  | "contains"
  | "starts_with"
  | "ends_with"
  | "is_empty"
  | "is_not_empty";

export interface FilterCondition {
  column: string;
  op: FilterOp;
  /** Omitted for the nullary ops (is_empty / is_not_empty). */
  value?: CellValue;
}

export interface QueryRequest {
  filter?: FilterCondition[];
  search?: string;
  orderBy?: string | null;
  orderDir?: "asc" | "desc";
  limit?: number;
  offset?: number;
}

/** One distinct value of a group-by column with its total count under the
 *  active filters. Returned highest-count first. */
export interface GroupCount {
  value: CellValue;
  count: number;
}

/** A foreign-key edge discovered from the team schema, used to follow
 *  relationships generically (e.g. a lead → its interactions). */
export interface ForeignKey {
  table: string;
  column: string;
  ref_table: string;
  ref_column: string;
}

/**
 * Client for the shared cloud team GLOBAL DB (cross-colony leads +
 * interactions). Hits the runtime's colony-independent ``/global/data/*``
 * proxy, which forwards to hive-backend ``/v1/global-db/*`` with the cloud
 * JWT (the main process prepends ``/api``, so paths here omit it — same
 * convention as colonyData.ts). Requires a signed-in session; the proxy
 * returns 401 when signed out.
 */
export const globalDataApi = {
  listTables: () => api.get<{ tables: TableOverview[] }>(`/global/data/tables`),

  /** Row-level changes since a cursor. No `since` = init call (cursor +
   *  coverage only, so the first poll doesn't report history as new). */
  listChanges: (since?: string | null) =>
    api.get<GlobalChangesResponse>(
      `/global/data/changes${since ? `?since=${encodeURIComponent(since)}` : ""}`,
    ),

  listRows: (
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
      `/global/data/tables/${encodeURIComponent(table)}/rows${qs ? `?${qs}` : ""}`,
    );
  },

  updateRow: (table: string, body: UpdateRowRequest) =>
    api.patch<{ updated: number }>(
      `/global/data/tables/${encodeURIComponent(table)}/rows`,
      body,
    ),

  /** Filtered / searched / sorted rows. Same response shape as listRows,
   *  but filters and search run server-side across the whole table. */
  query: (table: string, req: QueryRequest = {}) =>
    api.post<TableRowsResponse>(
      `/global/data/tables/${encodeURIComponent(table)}/query`,
      {
        filter: req.filter ?? [],
        search: req.search ?? null,
        order_by: req.orderBy ?? null,
        order_dir: req.orderDir ?? "asc",
        limit: req.limit ?? 100,
        offset: req.offset ?? 0,
      },
    ),

  /** Distinct values of ``groupBy`` with an accurate total count each, under
   *  the same server-side filter/search. Lets a board size + order its columns
   *  and show true per-column totals without loading every row. */
  groupCounts: (
    table: string,
    req: { groupBy: string; filter?: FilterCondition[]; search?: string },
  ) =>
    api.post<{ table: string; group_by: string; groups: GroupCount[] }>(
      `/global/data/tables/${encodeURIComponent(table)}/group-counts`,
      {
        group_by: req.groupBy,
        filter: req.filter ?? [],
        search: req.search ?? null,
      },
    ),

  /** Insert a record — true INSERT semantics. The pk is minted server-side
   *  when absent (for leads: canonical lead_id from LinkedIn/email). If the
   *  row already exists the runtime returns 409 with `{error: "conflict",
   *  pk}` — surfaced as an ApiError whose body carries the pk — instead of
   *  overwriting the existing row. */
  insertRow: (table: string, row: Record<string, CellValue>) =>
    api.post<{ inserted: number; pk: Record<string, CellValue> }>(
      `/global/data/tables/${encodeURIComponent(table)}/rows`,
      { row },
    ),

  /** Delete a record by primary key. */
  deleteRow: (table: string, pk: Record<string, CellValue>) =>
    api.delete<{ deleted: number }>(
      `/global/data/tables/${encodeURIComponent(table)}/rows`,
      { pk },
    ),

  /** Foreign-key edges across the team schema (for relationship views). */
  foreignKeys: () =>
    api.get<{ foreign_keys: ForeignKey[] }>(`/global/data/foreign-keys`),
};
