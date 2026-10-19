import type { CellValue, ColumnInfo } from "@/api/colonyData";

export type Row = Record<string, CellValue>;

/** Sentinel group key for the null/empty bucket (a leading space keeps it out
 *  of the range of real string values). Shared by the board and its data
 *  fetch so both agree on how a group value maps to a column. */
export const NULL_GROUP_KEY = " __null__";

/** Stable string key for a group column value — the null/empty bucket collapses
 *  to {@link NULL_GROUP_KEY}, everything else to its string form. */
export function groupKeyOf(value: CellValue): string {
  return value == null || value === "" ? NULL_GROUP_KEY : String(value);
}

// Tokens rendered upper-case (acronyms) or with specific casing (proper nouns)
// when humanizing a column name into a display label.
const LABEL_ACRONYMS = new Set([
  "id", "url", "api", "ip", "crm", "ui", "css", "html", "seo", "kpi",
  "arr", "mrr", "utc", "ai", "ml", "sql",
]);
const LABEL_SPECIAL: Record<string, string> = {
  linkedin: "LinkedIn",
  github: "GitHub",
  youtube: "YouTube",
};

/** Turn a raw column name into a readable display label: drop a trailing
 *  ``_at`` ("created_at" → "Created"), split on underscores, upper-case
 *  acronyms and fix proper nouns, then sentence-case ("linkedin_url" →
 *  "LinkedIn URL", "source_colony" → "Source colony"). Display-only — the raw
 *  column name stays the identifier everywhere it's used as a key/value. */
export function humanizeLabel(name: string): string {
  const parts = name.replace(/_at$/, "").split(/[_\s]+/).filter(Boolean);
  if (parts.length === 0) return name;
  const words = parts.map((p) => {
    const low = p.toLowerCase();
    return LABEL_SPECIAL[low] ?? (LABEL_ACRONYMS.has(low) ? low.toUpperCase() : low);
  });
  const joined = words.join(" ");
  return joined.charAt(0).toUpperCase() + joined.slice(1);
}

/** Display metadata for the distinct values of an enumerable column (e.g.
 *  ``leads.status`` backed by the ``lead_status`` lookup): the list is held in
 *  funnel order, and each entry carries a bubble ``color``. Built by the page
 *  from the lookup table and threaded into the grid/Kanban so ordering and
 *  coloring stay data-driven (never hardcoded in the UI). */
export interface ColumnOption {
  value: string;
  color?: string | null;
  /** Display name, when the source defines one (e.g. a team's own pipeline
   *  names its stages). Absent for inferred options — fall back to the value. */
  label?: string | null;
}

/** What to show for an option: its given label, else the raw value humanized —
 *  so a board never shows a user `qualified_lead` when the schema said
 *  "Qualified lead". */
export function optionLabel(opt: ColumnOption | undefined, value: CellValue): string {
  if (opt?.label) return opt.label;
  const raw = opt?.value ?? (value == null ? "" : String(value));
  return raw ? humanizeLabel(raw) : raw;
}

/** Per-column option lists, keyed by column name. */
export type ColumnOptions = Record<string, ColumnOption[]>;

/** Sort index of ``value`` within a column's options: its position when known
 *  (options are pre-ordered by funnel rank), after all known values when not,
 *  and last of all when null/empty. Drives group/board ordering by rank
 *  instead of first-seen. */
export function optionOrder(opts: ColumnOption[] | undefined, value: CellValue): number {
  if (value == null || value === "") return Number.POSITIVE_INFINITY;
  const i = opts?.findIndex((o) => o.value === String(value)) ?? -1;
  return i >= 0 ? i : Number.MAX_SAFE_INTEGER;
}

// Semantic colors for common lifecycle values; anything unmatched gets a
// stable hashed palette color so the same value is tinted identically on
// every page/session. Tones are muted and warm-leaning to sit within the
// hive/amber brand palette rather than reading as a saturated rainbow.
const INFER_SEMANTIC: Record<string, string> = {
  done: "#5a9c6e", success: "#5a9c6e", succeeded: "#5a9c6e", ok: "#5a9c6e",
  complete: "#5a9c6e", completed: "#5a9c6e", active: "#5a9c6e", ready: "#5a9c6e",
  error: "#cf6a5c", failed: "#cf6a5c", failure: "#cf6a5c", dead: "#cf6a5c", blocked: "#cf6a5c",
  pending: "#d9a441", running: "#d9a441", in_progress: "#d9a441", waiting: "#d9a441",
  queued: "#d9a441", retry: "#d9a441", paused: "#d9a441",
  skipped: "#8a8f99", cancelled: "#8a8f99", canceled: "#8a8f99",
  disabled: "#8a8f99", inactive: "#8a8f99", none: "#8a8f99",
};
// Warm, low-saturation categorical palette (honey / bronze / clay / taupe with
// two muted cool accents) so unmatched values stay distinguishable while
// remaining on-brand and calm.
const INFER_PALETTE = [
  "#c68a3e", "#b5763c", "#b08968", "#c07c5b", "#a98b4e", "#8f9a5b", "#9c7ba6", "#6e93a0",
];

export function inferredColor(value: string): string {
  const semantic = INFER_SEMANTIC[value.toLowerCase()];
  if (semantic) return semantic;
  let h = 0;
  for (let i = 0; i < value.length; i++) h = (h * 31 + value.charCodeAt(i)) >>> 0;
  return INFER_PALETTE[h % INFER_PALETTE.length];
}

/** Infer display-only {@link ColumnOptions} for enum-like columns from the
 *  loaded rows, for tables (e.g. colony-local DB) whose schema is flexible and
 *  has no lookup table to drive real options. A column qualifies when its
 *  values are short repeating strings with low cardinality — i.e. it reads as
 *  a status/category, not freeform text. Inference is per loaded page, so it's
 *  only for coloring value bubbles — callers must NOT let it gate editing
 *  (an unseen value would be wrongly unenterable). */
export function inferColumnOptions(
  columns: ColumnInfo[],
  rows: Row[],
  primaryKey: string[],
): ColumnOptions {
  // Too few rows → no repetition signal; don't guess.
  if (rows.length < 8) return {};
  const pk = new Set(primaryKey);
  const out: ColumnOptions = {};
  for (const c of columns) {
    if (pk.has(c.name) || isSystemColumn(c.name) || !isTextish(c)) continue;
    const distinct = new Set<string>();
    let nonNull = 0;
    let enumLike = true;
    for (const row of rows) {
      const v = row[c.name];
      if (v == null || v === "") continue;
      // Long values, whitespace-heavy prose, URLs, and bare numbers all read
      // as data, not categories.
      if (
        typeof v !== "string" ||
        v.length > 20 ||
        /\n/.test(v) ||
        /^https?:/i.test(v) ||
        /^-?\d+(\.\d+)?$/.test(v)
      ) {
        enumLike = false;
        break;
      }
      nonNull++;
      distinct.add(v);
      if (distinct.size > 8) {
        enumLike = false;
        break;
      }
    }
    // Require values to actually repeat, else it's freeform text.
    if (!enumLike || distinct.size === 0 || nonNull < distinct.size * 2) continue;
    out[c.name] = [...distinct]
      .sort()
      .map((value) => ({ value, color: inferredColor(value) }));
  }
  return out;
}

/** The option matching ``value`` (for color lookup), if any. */
export function findOption(
  opts: ColumnOption[] | undefined,
  value: CellValue,
): ColumnOption | undefined {
  if (value == null) return undefined;
  return opts?.find((o) => o.value === String(value));
}

/** Pull just the primary-key columns out of a row. */
export function extractPk(row: Row, primaryKey: string[]): Row {
  const out: Row = {};
  for (const k of primaryKey) out[k] = row[k];
  return out;
}

/** Stable string key for a row's primary key (React keys, dedupe, equality). */
export function pkKey(pk: Row, primaryKey: string[]): string {
  return primaryKey.map((p) => String(pk[p] ?? "")).join("␟");
}

/** True when ``row`` is the record identified by ``pk``. */
export function rowMatchesPk(row: Row, pk: Row, primaryKey: string[]): boolean {
  return primaryKey.every((p) => row[p] === pk[p]);
}

// Provenance/timestamp columns — framework-managed, always sink to the bottom
// of any display order, in this order.
const SYSTEM_ORDER = ["source_colony", "source_user", "created_at", "updated_at"];
const SYSTEM_COLS = new Set(SYSTEM_ORDER);

/** Framework-managed provenance/timestamp column (auto-stamped/defaulted, not
 *  user-entered) — e.g. hidden on the "new record" draft form. */
export function isSystemColumn(name: string): boolean {
  return SYSTEM_COLS.has(name);
}

/** Deterministic within-group order so cards/rows keep their place across
 *  polls after an edit. Sorts newest-first by ``created_at`` when present —
 *  it's immutable, so editing a row never moves it — with the primary key as a
 *  stable tiebreaker. Without a stable key, same-group rows fall back to
 *  Postgres physical order, which an UPDATE reshuffles (the "jumping" bug). */
export function stableRowComparator(
  columns: ColumnInfo[],
  primaryKey: string[],
): (a: Row, b: Row) => number {
  const hasCreated = columns.some((c) => c.name === "created_at");
  const pkOf = (r: Row) => primaryKey.map((p) => String(r[p] ?? "")).join("␟");
  return (a, b) => {
    if (hasCreated) {
      const av = String(a.created_at ?? "");
      const bv = String(b.created_at ?? "");
      if (av !== bv) return av < bv ? 1 : -1; // desc → newest first
    }
    const ak = pkOf(a);
    const bk = pkOf(b);
    return ak < bk ? -1 : ak > bk ? 1 : 0;
  };
}

// Curated display order for the tables we ship. Columns not listed keep their
// natural (DDL) order, slotted after the curated ones but ahead of the system
// columns. Other tables fall back to natural order (system columns still sink).
const PREFERRED_ORDER: Record<string, string[]> = {
  leads: ["lead_id", "name", "email", "company", "title", "linkedin_url", "status", "note"],
  interactions: ["interaction_id", "lead_id", "channel", "direction", "occurred_at", "summary"],
};

/** Order columns for display: curated columns first (per table), then any
 *  other (e.g. agent-added) columns in their natural order, then the
 *  provenance/timestamp columns last. Stable — never drops or renames a
 *  column, only reorders. Applied at the page level so the table, Kanban
 *  cards, and the record detail panel all show one consistent order. */
export function orderColumns(columns: ColumnInfo[], table: string): ColumnInfo[] {
  const pref = new Map((PREFERRED_ORDER[table] ?? []).map((n, i) => [n, i]));
  const sys = new Map(SYSTEM_ORDER.map((n, i) => [n, i]));
  const bucket = (n: string) => (sys.has(n) ? 2 : pref.has(n) ? 0 : 1);
  const within = (n: string) => sys.get(n) ?? pref.get(n) ?? 0;
  return columns
    .map((c, i) => ({ c, i }))
    .sort(
      (a, b) =>
        bucket(a.c.name) - bucket(b.c.name) ||
        within(a.c.name) - within(b.c.name) ||
        a.i - b.i, // stable within the "other" bucket: keep natural order
    )
    .map((x) => x.c);
}

/** The column to use as a record's headline (card title, panel title).
 *  Prefers a ``name``/``title`` field, else the first non-PK text column,
 *  else the first column. */
export function titleColumn(columns: ColumnInfo[], primaryKey: string[]): string {
  const pk = new Set(primaryKey);
  const byName = columns.find(
    (c) => (c.name === "name" || c.name === "title") && !pk.has(c.name),
  );
  if (byName) return byName.name;
  const firstText = columns.find(
    (c) => !pk.has(c.name) && isTextish(c) && !SYSTEM_COLS.has(c.name),
  );
  if (firstText) return firstText.name;
  return columns[0]?.name ?? "";
}

/** A record's headline from one or more columns.
 *
 *  Exists because a person's name is two columns: picking a single one shows
 *  "Wolfgang" where the user expects "Wolfgang Rathgeb". `parts` comes from the
 *  server (`title_parts`), so which columns compose a name stays a property of
 *  the schema rather than a guess made here.
 *
 *  Empty parts are dropped rather than joined, so a mononym renders as the bare
 *  first name with no trailing space. Falls back to `fallbackCol` when the
 *  server sent no parts, or when every part is empty. */
export function titleFromParts(
  row: Record<string, unknown>,
  parts: string[] | null | undefined,
  fallbackCol: string,
): string {
  if (parts?.length) {
    const joined = parts
      .map((p) => {
        const v = row[p];
        return v == null ? "" : String(v).trim();
      })
      .filter(Boolean)
      .join(" ");
    if (joined) return joined;
  }
  const v = row[fallbackCol];
  return v == null ? "" : String(v).trim();
}

function isTextish(c: ColumnInfo): boolean {
  const t = (c.type || "").toLowerCase();
  return t === "" || t.includes("text") || t.includes("char") || t.includes("enum");
}

/** Columns that make sense to group a Kanban board by: short text/enum-like
 *  fields, excluding the primary key, system columns, and free-text-looking
 *  fields (email, url, summary, notes…). */
export function groupableColumns(columns: ColumnInfo[], primaryKey: string[]): string[] {
  const pk = new Set(primaryKey);
  return columns
    .filter((c) => !pk.has(c.name) && !SYSTEM_COLS.has(c.name) && isTextish(c))
    .filter((c) => !/(email|url|summary|note|description|address)/i.test(c.name))
    .map((c) => c.name);
}

/** A sensible default group column for a Kanban board. */
export function defaultGroupColumn(columns: ColumnInfo[], primaryKey: string[]): string | null {
  const groupable = groupableColumns(columns, primaryKey);
  const preferred = ["status", "stage", "pipeline", "priority", "type", "category", "state"];
  for (const p of preferred) {
    if (groupable.includes(p)) return p;
  }
  return groupable[0] ?? null;
}
