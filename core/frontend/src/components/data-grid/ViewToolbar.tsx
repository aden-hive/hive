import { useState } from "react";
import {
  Filter,
  LayoutGrid,
  Loader2,
  Maximize2,
  Minimize2,
  Plus,
  Table as TableIcon,
} from "lucide-react";
import type { ColumnInfo } from "@/api/colonyData";
import type { FilterCondition } from "@/api/globalData";
import { SearchInput } from "@/components/SearchInput";
import { FilterPanel } from "./FilterPanel";
import { GroupMenu } from "./GroupMenu";

export type ViewMode = "table" | "kanban";

interface ViewToolbarProps {
  view: ViewMode;
  onViewChange: (v: ViewMode) => void;

  search: string;
  onSearchChange: (s: string) => void;
  searching?: boolean;

  columns: ColumnInfo[];
  filters: FilterCondition[];
  onFiltersChange: (f: FilterCondition[]) => void;

  /** The shared grouping column (drives both the Kanban board and the grouped
   *  Table). ``null`` = ungrouped, only reachable in Table view. */
  groupBy: string | null;
  groupableColumns: string[];
  onGroupByChange: (c: string | null) => void;

  onAddRecord: () => void;
  adding?: boolean;

  fullscreen: boolean;
  onToggleFullscreen: () => void;
}

const TABS: { id: ViewMode; label: string; Icon: typeof TableIcon }[] = [
  { id: "kanban", label: "Kanban", Icon: LayoutGrid },
  { id: "table", label: "Table", Icon: TableIcon },
];

/** The view-level control strip above a table: view tabs + fullscreen on the
 *  left; data controls (search, filter, group, add) on the right. */
export function ViewToolbar({
  view,
  onViewChange,
  search,
  onSearchChange,
  searching,
  columns,
  filters,
  onFiltersChange,
  groupBy,
  groupableColumns,
  onGroupByChange,
  onAddRecord,
  adding,
  fullscreen,
  onToggleFullscreen,
}: ViewToolbarProps) {
  const [filterOpen, setFilterOpen] = useState(false);

  return (
    <div className="flex items-center justify-between gap-2 flex-wrap">
      {/* Left: view tabs + fullscreen */}
      <div className="flex items-center gap-1">
        <div className="flex items-center gap-0.5 p-0.5 rounded-lg bg-muted/40">
          {TABS.map(({ id, label, Icon }) => (
            <button
              key={id}
              onClick={() => onViewChange(id)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${
                view === id
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {label}
            </button>
          ))}
        </div>
        <button
          onClick={onToggleFullscreen}
          title={fullscreen ? "Exit expanded view (Esc)" : "Expand view"}
          aria-label={fullscreen ? "Exit expanded view" : "Expand view"}
          className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors"
        >
          {fullscreen ? (
            <Minimize2 className="w-4 h-4" />
          ) : (
            <Maximize2 className="w-4 h-4" />
          )}
        </button>
      </div>

      {/* Right: data controls */}
      <div className="flex items-center gap-1.5">
        <SearchInput
          value={search}
          onChange={onSearchChange}
          loading={searching}
          placeholder="Search…"
          className="w-44"
        />

        {groupableColumns.length > 0 && (
          // One shared group-by control. "No grouping" is only offered in Table
          // view — the Kanban board always needs a group column.
          <GroupMenu
            value={groupBy}
            options={groupableColumns}
            allowNone={view === "table"}
            onChange={onGroupByChange}
          />
        )}

        <div className="relative">
          <button
            onClick={() => setFilterOpen((o) => !o)}
            className={`flex items-center gap-1.5 h-9 px-2.5 rounded-lg border text-xs font-medium transition-colors ${
              filters.length > 0
                ? "border-primary/40 bg-primary/10 text-primary"
                : "border-border/60 text-muted-foreground hover:text-foreground hover:bg-muted/30"
            }`}
          >
            <Filter className="w-3.5 h-3.5" />
            Filter
            {filters.length > 0 && (
              <span className="text-[10px] tabular-nums bg-primary/20 px-1 rounded">
                {filters.length}
              </span>
            )}
          </button>
          {filterOpen && (
            <FilterPanel
              columns={columns}
              filters={filters}
              onChange={onFiltersChange}
              onClose={() => setFilterOpen(false)}
            />
          )}
        </div>

        <button
          onClick={onAddRecord}
          disabled={adding}
          className="flex items-center gap-1.5 h-9 px-3 rounded-lg bg-primary text-primary-foreground text-xs font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
        >
          {adding ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <Plus className="w-3.5 h-3.5" />
          )}
          New record
        </button>
      </div>
    </div>
  );
}
