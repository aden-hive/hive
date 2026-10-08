import { useEffect, useMemo, useRef, useState } from "react";
import { Inbox, Loader2, Search } from "lucide-react";
import type { CellValue, ColumnInfo } from "@/api/colonyData";
import { displayValue, ValueBadge } from "./EditableCell";
import {
  type ColumnOption,
  type ColumnOptions,
  extractPk,
  findOption,
  groupKeyOf,
  NULL_GROUP_KEY,
  optionLabel,
  optionOrder,
  pkKey,
  type Row,
  titleColumn,
  titleFromParts,
} from "./gridUtils";

interface KanbanViewProps {
  columns: ColumnInfo[];
  rows: Row[];
  primaryKey: string[];
  groupColumn: string;
  /** Columns whose values join to form the card headline, when one column can't
   *  express it — a person's name is first + last, and picking a single column
   *  shows only half of it. Supplied by the caller from the server schema; omit
   *  to let the board pick one column by its own heuristic. */
  titleParts?: string[] | null;
  /** Fields to preview on each card, in priority order. Names that aren't in
   *  ``columns`` (or that are the pk/title/group column) are ignored, so a
   *  caller can name a field this entity happens not to project. Omit to let
   *  the board pick the first few columns itself. */
  previewColumns?: string[];
  /** Per-column display metadata (e.g. status colors + funnel order). */
  columnOptions?: ColumnOptions;
  /** Accurate total row count per group value (keyed by {@link groupKeyOf}),
   *  from the server GROUP BY. When a group's true total exceeds the rows
   *  actually loaded, the column shows the true total and a "more" hint rather
   *  than an undercount of what happens to be on the board. */
  groupTotals?: Map<string, number> | null;
  /** Card keys (gridUtils.pkKey) to tint as recently changed. The caller
   *  owns the lifecycle (add on change, drop to fade); the board only paints. */
  highlightKeys?: Set<string>;
  /** Fetch the next page of cards for one column, appending them to ``rows``.
   *  Resolves with how many rows the server returned — 0 means the column is
   *  exhausted (its total was stale), which stops the board asking again. */
  onLoadMore?: (groupKey: string, groupValue: CellValue, loaded: number) => Promise<number>;
  /** Group keys with a page request in flight, so those columns show progress. */
  loadingGroups?: Set<string>;
  /** Focus the toolbar search field — the escape hatch offered by a deep
   *  column's footer, so acting on it doesn't mean scrolling back to the top. */
  onFocusSearch?: () => void;
  /** Move a card to a new value for the group column. */
  onMoveCard: (pk: Row, newValue: CellValue) => Promise<void>;
  onCardClick: (pk: Row) => void;
}

const NULL_KEY = NULL_GROUP_KEY;

/** How many cards a column renders before the user has to scroll for more. */
const CARD_PAGE = 25;

/** Preview lines on one card. A hard cap, so cards stay the same height however
 *  complete a record is — the ranking decides WHICH fields, this decides how
 *  many. */
const MAX_CARD_FIELDS = 3;

/** Cards loaded in one column before its footer starts steering toward search.
 *  Under this, scrolling is a reasonable way to browse and the board stays
 *  quiet; past it, scrolling is losing to search and the footer says so. */
const NUDGE_AFTER = 300;

/** Kanban board: cards grouped into columns by ``groupColumn``. Drag a card
 *  onto another column to set that field's value. Generic over any table —
 *  the group column is chosen in the toolbar. */
export function KanbanView({
  columns,
  rows,
  primaryKey,
  groupColumn,
  titleParts,
  previewColumns,
  columnOptions,
  groupTotals,
  highlightKeys,
  onLoadMore,
  loadingGroups,
  onFocusSearch,
  onMoveCard,
  onCardClick,
}: KanbanViewProps) {
  const [dragging, setDragging] = useState<Row | null>(null);
  const [dragOver, setDragOver] = useState<string | null>(null);

  const title = useMemo(() => titleColumn(columns, primaryKey), [columns, primaryKey]);
  const titleCol = useMemo(
    () => columns.find((c) => c.name === title) ?? null,
    [columns, title],
  );
  // Candidate fields to preview on each card — the caller's ranking when it has
  // one, else column order. Deliberately NOT truncated to MAX_CARD_FIELDS: each
  // card takes the first few of these it actually has values for, so a sparse
  // record falls through to whatever it does know rather than rendering short.
  //
  // Every column feeding the headline is skipped, not just the one `title`
  // names — otherwise a person's last name renders again as a preview field
  // directly under the full name it is already part of.
  const previewCols = useMemo(() => {
    const skip = new Set([...primaryKey, title, groupColumn, ...(titleParts ?? [])]);
    return previewColumns
      ? previewColumns
          .filter((n) => !skip.has(n))
          .map((n) => columns.find((c) => c.name === n))
          .filter((c): c is ColumnInfo => !!c)
      : columns.filter((c) => !skip.has(c.name));
  }, [columns, primaryKey, title, groupColumn, titleParts, previewColumns]);
  // Fallback shown only when a card has none of its preview fields filled in
  // (e.g. a lead with no title/company): its provenance, so the card isn't a
  // bare name.
  const fallbackCol = useMemo(
    () => columns.find((c) => c.name === "source_colony") ?? null,
    [columns],
  );

  const groupOpts = columnOptions?.[groupColumn];

  // Group rows by the group column's value. Ordered by option (funnel) order
  // when available, else first-seen; null/empty always last.
  const groups = useMemo(() => {
    const map = new Map<string, { label: string; value: CellValue; rows: Row[] }>();
    // Pre-seed a column for every defined option so statuses with no leads
    // still appear on the board (and can be dropped onto).
    for (const opt of groupOpts ?? []) {
      map.set(opt.value, { label: optionLabel(opt, opt.value), value: opt.value, rows: [] });
    }
    // Rows render in the order the server returned them. The CRM grid always
    // emits `ORDER BY <entity default_sort> NULLS LAST, "__pk" DESC` — a total
    // order, so it's already stable across refetches. Re-sorting here would
    // pick a *different* column than the one the server paged by, which
    // interleaves newly paged-in cards above the user's scroll position.
    for (const row of rows) {
      const raw = row[groupColumn];
      const key = groupKeyOf(raw);
      if (!map.has(key)) {
        map.set(key, {
          label: key === NULL_KEY ? `No ${groupColumn}` : String(raw),
          value: key === NULL_KEY ? null : raw,
          rows: [],
        });
      }
      map.get(key)!.rows.push(row);
    }
    return [...map.entries()]
      .sort((a, b) => optionOrder(groupOpts, a[1].value) - optionOrder(groupOpts, b[1].value))
      // ``total`` is the accurate server count; fall back to the loaded count
      // when this group isn't in the totals map (e.g. totals not yet loaded).
      .map(([key, g]) => ({ key, ...g, total: groupTotals?.get(key) ?? g.rows.length }));
  }, [rows, groupColumn, groupOpts, groupTotals]);

  const handleDrop = async (target: { key: string; value: CellValue }) => {
    setDragOver(null);
    const card = dragging;
    setDragging(null);
    if (!card) return;
    const currentKey = groupKeyOf(card[groupColumn]);
    if (currentKey === target.key) return; // dropped in same column
    if (target.key === NULL_KEY) return; // don't clear via drag
    await onMoveCard(extractPk(card, primaryKey), target.value);
  };

  if (groups.length === 0) {
    return (
      <div className="text-center text-muted-foreground py-16 text-sm">
        No records to board.
      </div>
    );
  }

  return (
    <div className="flex gap-3 overflow-x-auto pb-2 min-h-0">
      {groups.map((g) => (
        <KanbanColumn
          key={g.key}
          group={g}
          groupOpts={groupOpts}
          highlightKeys={highlightKeys}
          onLoadMore={onLoadMore}
          isLoadingMore={loadingGroups?.has(g.key) ?? false}
          onFocusSearch={onFocusSearch}
          primaryKey={primaryKey}
          title={title}
          titleCol={titleCol}
          titleParts={titleParts}
          previewCols={previewCols}
          fallbackCol={fallbackCol}
          isDragOver={dragOver === g.key}
          onDragOver={() => setDragOver(g.key)}
          onDragLeave={() => setDragOver((k) => (k === g.key ? null : k))}
          onDrop={() => handleDrop(g)}
          onCardDragStart={(row) => setDragging(row)}
          onCardDragEnd={() => {
            setDragging(null);
            setDragOver(null);
          }}
          onCardClick={onCardClick}
        />
      ))}
    </div>
  );
}

interface KanbanColumnProps {
  group: { key: string; label: string; value: CellValue; rows: Row[]; total: number };
  groupOpts: ColumnOption[] | undefined;
  highlightKeys?: Set<string>;
  onLoadMore?: (groupKey: string, groupValue: CellValue, loaded: number) => Promise<number>;
  isLoadingMore: boolean;
  onFocusSearch?: () => void;
  primaryKey: string[];
  title: string;
  titleCol: ColumnInfo | null;
  titleParts?: string[] | null;
  previewCols: ColumnInfo[];
  fallbackCol: ColumnInfo | null;
  isDragOver: boolean;
  onDragOver: () => void;
  onDragLeave: () => void;
  onDrop: () => void;
  onCardDragStart: (row: Row) => void;
  onCardDragEnd: () => void;
  onCardClick: (pk: Row) => void;
}

/** A single Kanban column. Renders only the first ``CARD_PAGE`` cards and
 *  reveals another page each time the user nears the bottom, so a column with
 *  thousands of rows doesn't mount every card up front. Once every loaded card
 *  is revealed, the same sentinel fetches the next page from the server, so
 *  scrolling always produces more cards while any remain. */
function KanbanColumn({
  group,
  groupOpts,
  highlightKeys,
  onLoadMore,
  isLoadingMore,
  onFocusSearch,
  primaryKey,
  title,
  titleCol,
  titleParts,
  previewCols,
  fallbackCol,
  isDragOver,
  onDragOver,
  onDragLeave,
  onDrop,
  onCardDragStart,
  onCardDragEnd,
  onCardClick,
}: KanbanColumnProps) {
  const [visible, setVisible] = useState(CARD_PAGE);
  // Set when a fetch returns nothing even though ``total`` promised more (a
  // stale GROUP BY count), so the sentinel stops re-asking forever. Both this
  // and the in-flight flag are mirrored in refs because the observer callback
  // reads them synchronously — state alone is still stale during the render
  // between a request settling and the flag landing, which is exactly when a
  // duplicate request would fire.
  const [exhausted, setExhausted] = useState(false);
  const exhaustedRef = useRef(false);
  const fetchingRef = useRef(false);
  // ``loaded`` = cards fetched onto the board for this group; ``total`` = the
  // accurate server-side count; ``visible`` = how many loaded cards are mounted.
  // Scrolling walks visible → loaded, then asks the server for loaded → total.
  const loaded = group.rows.length;
  const total = group.total;
  const shown = visible >= loaded ? group.rows : group.rows.slice(0, visible);
  const hasMoreLoaded = visible < loaded;
  const canFetchMore = !hasMoreLoaded && !exhausted && !!onLoadMore && loaded < total;
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  // A page arriving (or the total growing) makes it worth asking again after a
  // previous request came back empty.
  useEffect(() => {
    exhaustedRef.current = false;
    setExhausted(false);
  }, [loaded, total]);

  // Advance when the bottom sentinel scrolls into view: mount already-loaded
  // cards first, then fetch the next page once they're all mounted. An observer
  // (vs. an onScroll handler) is used because the actual scroll container is an
  // ancestor of this column, not the column itself, so a local scroll listener
  // would never fire.
  useEffect(() => {
    if (!hasMoreLoaded && !canFetchMore) return;
    const el = sentinelRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (!entries[0]?.isIntersecting) return;
        if (hasMoreLoaded) {
          setVisible((v) => Math.min(v + CARD_PAGE, loaded));
        } else if (canFetchMore && !fetchingRef.current && !exhaustedRef.current) {
          fetchingRef.current = true;
          void onLoadMore?.(group.key, group.value, loaded)
            .then((added) => {
              if (added === 0) {
                exhaustedRef.current = true;
                setExhausted(true);
              }
            })
            .finally(() => {
              fetchingRef.current = false;
            });
        }
      },
      { rootMargin: "300px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [hasMoreLoaded, canFetchMore, loaded, visible, group.key, group.value, onLoadMore]);

  const opt = group.key === NULL_KEY ? undefined : findOption(groupOpts, group.value);

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        onDragOver();
      }}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      className={`flex flex-col w-64 flex-shrink-0 rounded-lg border transition-colors ${
        isDragOver ? "border-primary/50 bg-primary/5" : "border-border/50 bg-muted/15"
      }`}
    >
      <div className="flex items-center justify-between gap-1 px-2.5 py-2 border-b border-border/40">
        {opt ? (
          <ValueBadge label={group.label} color={opt.color} />
        ) : (
          <span className="text-xs font-semibold text-foreground/90 truncate">
            {group.label}
          </span>
        )}
        {/* The column count is how many records exist, not how many happen to be
            fetched — cards stream in on scroll, so a loaded/total pair would read
            as a cap. How much is loaded belongs on the scroll sentinel below. */}
        <span
          className="text-[10px] tabular-nums text-muted-foreground/70 bg-muted/50 px-1.5 rounded-full"
          title={loaded < total ? `${loaded} of ${total} loaded` : undefined}
        >
          {total.toLocaleString()}
        </span>
      </div>
      <div className="flex flex-col gap-1.5 p-1.5 overflow-y-auto">
        {shown.map((row) => {
          const hasVal = (c: ColumnInfo) => row[c.name] != null && row[c.name] !== "";
          const filled = previewCols.filter(hasVal).slice(0, MAX_CARD_FIELDS);
          // Nothing to preview (e.g. no title/company) → show provenance so the
          // card isn't just a bare name.
          const fields =
            filled.length > 0 ? filled : fallbackCol && hasVal(fallbackCol) ? [fallbackCol] : [];
          const cardKey = pkKey(extractPk(row, primaryKey), primaryKey);
          // Recently-changed tint; transition-all makes the fade-out soft.
          const highlighted = highlightKeys?.has(cardKey) ?? false;
          return (
            <button
              key={cardKey}
              draggable
              onDragStart={() => onCardDragStart(row)}
              onDragEnd={onCardDragEnd}
              onClick={() => onCardClick(extractPk(row, primaryKey))}
              className={`text-left rounded-md border px-2.5 py-2 hover:border-primary/40 hover:shadow-sm cursor-grab active:cursor-grabbing transition-all ${
                highlighted
                  ? "border-emerald-500/60 bg-emerald-500/10"
                  : "border-border/50 bg-card"
              }`}
            >
              <div className="text-xs font-medium text-foreground truncate">
                {(titleParts?.length
                  ? titleFromParts(row, titleParts, title)
                  : titleCol && displayValue(row[title], titleCol)) || "Untitled"}
              </div>
              {fields.map((c) => (
                <div
                  key={c.name}
                  className="mt-1 text-[10px] text-muted-foreground truncate"
                >
                  <span className="text-muted-foreground/50">{c.label ?? c.name}:</span>{" "}
                  {displayValue(row[c.name], c)}
                </div>
              ))}
            </button>
          );
        })}
        {loaded === 0 && (
          <div
            className={`m-1 flex flex-col items-center justify-center gap-1.5 rounded-md border border-dashed py-8 transition-colors ${
              isDragOver
                ? "border-primary/50 text-primary/70"
                : "border-border/50 text-muted-foreground/50"
            }`}
          >
            <Inbox className="w-4 h-4" aria-hidden />
            <span className="text-[10px] font-medium">No records</span>
            <span className="text-[9px] text-muted-foreground/40">Drag a card here</span>
          </div>
        )}
        {(hasMoreLoaded || loaded < total) && (
          <div
            ref={sentinelRef}
            className="flex flex-col items-center gap-1 py-2 text-center text-[10px] text-muted-foreground/60"
          >
            {isLoadingMore ? (
              <span className="inline-flex items-center gap-1.5">
                <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
                Loading more…
              </span>
            ) : (
              <span className="tabular-nums">
                {loaded.toLocaleString()} of {total.toLocaleString()}
              </span>
            )}
            {/* Only past a few hundred cards is scrolling actually losing to
                search — nag then, not while someone browses a short column. */}
            {loaded >= NUDGE_AFTER && !exhausted && onFocusSearch && (
              <button
                onClick={onFocusSearch}
                className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 underline decoration-dotted underline-offset-2 transition-colors hover:bg-muted/40 hover:text-foreground"
              >
                <Search className="h-2.5 w-2.5 flex-shrink-0" aria-hidden />
                search will be faster than scrolling
              </button>
            )}
            {exhausted && <span>Nothing more to load — that count may be stale.</span>}
          </div>
        )}
      </div>
    </div>
  );
}
