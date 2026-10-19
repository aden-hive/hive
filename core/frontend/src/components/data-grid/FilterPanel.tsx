import { useEffect, useRef } from "react";
import { Plus, Trash2, X } from "lucide-react";
import type { ColumnInfo } from "@/api/colonyData";
import type { FilterCondition, FilterOp } from "@/api/globalData";
import { humanizeLabel } from "./gridUtils";
import { MenuSelect } from "./MenuSelect";

const OPS: { value: FilterOp; label: string; nullary?: boolean }[] = [
  { value: "eq", label: "is" },
  { value: "ne", label: "is not" },
  { value: "contains", label: "contains" },
  { value: "starts_with", label: "starts with" },
  { value: "ends_with", label: "ends with" },
  { value: "gt", label: ">" },
  { value: "gte", label: "≥" },
  { value: "lt", label: "<" },
  { value: "lte", label: "≤" },
  { value: "is_empty", label: "is empty", nullary: true },
  { value: "is_not_empty", label: "is not empty", nullary: true },
];

const NULLARY = new Set(OPS.filter((o) => o.nullary).map((o) => o.value));

/** Column names people are most likely to filter on, in priority order.
 *  Covers the CRM tables: leads (email/name/…), interactions (channel/…),
 *  lead_status (status). */
const PREFERRED = [
  "email",
  "name",
  "full_name",
  "title",
  "company",
  "status",
  "channel",
  "direction",
  "summary",
];

/** Id/reference columns nobody filters by — skipped when falling back. */
const isIdLike = (name: string) => {
  const n = name.toLowerCase();
  return n === "id" || n.endsWith("_id");
};

/** Pick a sensible default column to filter on instead of always grabbing the
 *  first column (which is usually the id / primary key that nobody filters by). */
function defaultFilterColumn(columns: ColumnInfo[]): string {
  const byName = columns.find((c) => PREFERRED.includes(c.name.toLowerCase()));
  if (byName) return byName.name;
  const partial = columns.find((c) =>
    PREFERRED.some((p) => c.name.toLowerCase().includes(p)),
  );
  if (partial) return partial.name;
  const meaningful = (c: ColumnInfo) => !c.pk && !isIdLike(c.name);
  const textCol = columns.find((c) => meaningful(c) && c.type.toUpperCase().includes("TEXT"));
  if (textCol) return textCol.name;
  const nonId = columns.find(meaningful) ?? columns.find((c) => !isIdLike(c.name));
  return (nonId ?? columns[0])?.name ?? "";
}

interface FilterPanelProps {
  columns: ColumnInfo[];
  filters: FilterCondition[];
  onChange: (filters: FilterCondition[]) => void;
  onClose: () => void;
}

/** Popover for building server-side filter conditions. Anchored by the
 *  caller; closes on outside-click or Escape. */
export function FilterPanel({ columns, filters, onChange, onClose }: FilterPanelProps) {
  const ref = useRef<HTMLDivElement | null>(null);
  const filtersRef = useRef(filters);
  filtersRef.current = filters;
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  // Seed one editable row when opening an empty panel so the user sees the
  // column/operator/value controls immediately (no "click Add filter first"
  // step). On close, drop any row that was never filled in so the filter
  // count and query stay honest.
  useEffect(() => {
    if (filtersRef.current.length === 0 && columns.length > 0) {
      onChangeRef.current([
        { column: defaultFilterColumn(columns), op: "contains", value: "" },
      ]);
    }
    return () => {
      const complete = filtersRef.current.filter(
        (f) => NULLARY.has(f.op) || String(f.value ?? "").trim() !== "",
      );
      if (complete.length !== filtersRef.current.length) onChangeRef.current(complete);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const update = (i: number, patch: Partial<FilterCondition>) => {
    onChange(filters.map((f, idx) => (idx === i ? { ...f, ...patch } : f)));
  };
  const remove = (i: number) => onChange(filters.filter((_, idx) => idx !== i));
  const add = () =>
    onChange([...filters, { column: defaultFilterColumn(columns), op: "contains", value: "" }]);

  return (
    <div
      ref={ref}
      className="absolute right-0 top-full mt-1.5 z-30 w-[420px] rounded-lg border border-border/60 bg-card shadow-xl p-3"
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-foreground/90">Filters</span>
        <button
          onClick={onClose}
          className="p-1 rounded-md text-muted-foreground/60 hover:text-foreground hover:bg-muted/50"
          aria-label="Close filters"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {filters.length === 0 ? (
        <p className="text-[11px] text-muted-foreground py-2">
          No filters. Add one to narrow this table.
        </p>
      ) : (
        <div className="flex flex-col gap-1.5">
          {filters.map((f, i) => {
            const nullary = NULLARY.has(f.op);
            return (
              <div key={i} className="flex items-center gap-1.5">
                <span className="text-[10px] text-muted-foreground w-8 text-right">
                  {i === 0 ? "Where" : "and"}
                </span>
                <MenuSelect
                  ariaLabel="Filter column"
                  className="flex-1 min-w-0"
                  value={f.column}
                  onChange={(v) => update(i, { column: v })}
                  options={columns.map((c) => ({ value: c.name, label: humanizeLabel(c.name) }))}
                />
                <MenuSelect
                  ariaLabel="Filter operator"
                  className="w-24 flex-shrink-0"
                  value={f.op}
                  onChange={(v) => update(i, { op: v as FilterOp })}
                  options={OPS.map((o) => ({ value: o.value, label: o.label }))}
                />
                <input
                  type="text"
                  value={nullary ? "" : String(f.value ?? "")}
                  disabled={nullary}
                  onChange={(e) => update(i, { value: e.target.value })}
                  placeholder="value"
                  className="w-24 h-7 px-2 rounded-md border border-border/60 bg-background text-[11px] focus:outline-none focus:border-primary/40 disabled:opacity-40 disabled:bg-muted/30"
                />
                <button
                  onClick={() => remove(i)}
                  className="p-1 rounded-md text-muted-foreground/60 hover:text-destructive hover:bg-destructive/10"
                  aria-label="Remove filter"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            );
          })}
        </div>
      )}

      <div className="flex items-center justify-between mt-2.5 pt-2.5 border-t border-border/40">
        <button
          onClick={add}
          className="flex items-center gap-1 text-[11px] font-medium text-primary hover:text-primary/80"
        >
          <Plus className="w-3.5 h-3.5" /> Add filter
        </button>
        {filters.length > 0 && (
          <button
            onClick={() => onChange([])}
            className="text-[11px] text-muted-foreground hover:text-foreground"
          >
            Clear all
          </button>
        )}
      </div>
    </div>
  );
}
