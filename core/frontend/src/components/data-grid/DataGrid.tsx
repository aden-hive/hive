import { useCallback } from "react";
import { ArrowDown, ArrowUp, Loader2 } from "lucide-react";
import type { CellValue, ColumnInfo } from "@/api/colonyData";
import { EditableCell } from "./EditableCell";

export type SortDir = "asc" | "desc";

export interface DataGridProps {
  columns: ColumnInfo[];
  rows: Record<string, CellValue>[];
  /** Columns that form the primary key — used to identify rows for
   *  edits and rendered non-editable. */
  primaryKey: string[];

  orderBy: string | null;
  orderDir: SortDir;
  onSortChange: (column: string | null, dir: SortDir) => void;

  /** If provided, non-PK cells become click-to-edit. The handler is
   *  called with the PK values for the row, the column name, and the
   *  parsed new value. A rejected promise surfaces as a cell-level
   *  error tooltip without dirtying the rest of the grid. */
  onCellEdit?: (
    pk: Record<string, CellValue>,
    column: string,
    newValue: CellValue,
  ) => Promise<void>;

  loading?: boolean;
  emptyMessage?: string;
}

/** Airtable-style editable grid. Self-contained — pass columns + rows
 *  and wire up sort/edit callbacks to drive server-side state. */
export function DataGrid({
  columns,
  rows,
  primaryKey,
  orderBy,
  orderDir,
  onSortChange,
  onCellEdit,
  loading = false,
  emptyMessage = "No rows.",
}: DataGridProps) {
  const handleHeaderClick = useCallback(
    (col: string) => {
      if (orderBy === col) {
        // Same column: flip direction, then on the 3rd click clear sort.
        if (orderDir === "asc") onSortChange(col, "desc");
        else onSortChange(null, "asc");
      } else {
        onSortChange(col, "asc");
      }
    },
    [orderBy, orderDir, onSortChange],
  );

  const pkSet = new Set(primaryKey);

  const extractPk = (row: Record<string, CellValue>): Record<string, CellValue> => {
    const out: Record<string, CellValue> = {};
    for (const k of primaryKey) out[k] = row[k];
    return out;
  };

  return (
    <div className="relative border border-border/60 rounded-lg overflow-hidden">
      {loading && (
        <div className="absolute top-1.5 right-1.5 z-10 text-muted-foreground">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
        </div>
      )}
      <div className="overflow-auto max-h-[60vh]">
        <table className="text-[11px] w-full border-collapse">
          <thead className="sticky top-0 z-[1] bg-card/95 backdrop-blur-sm">
            <tr>
              {columns.map((c) => {
                const isPk = pkSet.has(c.name);
                const active = orderBy === c.name;
                return (
                  <th
                    key={c.name}
                    onClick={() => handleHeaderClick(c.name)}
                    className="text-left font-semibold text-foreground/90 border-b border-border/60 px-2 py-1.5 cursor-pointer hover:bg-muted/40 select-none whitespace-nowrap"
                    title={`${c.name}${c.type ? ` (${c.type})` : ""}${isPk ? " — primary key" : ""}${c.notnull ? " — NOT NULL" : ""}`}
                  >
                    <span className="inline-flex items-center gap-1">
                      {isPk && (
                        <span className="text-[8px] uppercase tracking-wider bg-primary/15 text-primary px-1 rounded">
                          pk
                        </span>
                      )}
                      <span>{c.name}</span>
                      {active &&
                        (orderDir === "asc" ? (
                          <ArrowUp className="w-3 h-3 text-primary" />
                        ) : (
                          <ArrowDown className="w-3 h-3 text-primary" />
                        ))}
                    </span>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && !loading ? (
              <tr>
                <td
                  colSpan={Math.max(columns.length, 1)}
                  className="text-center text-muted-foreground py-6"
                >
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              rows.map((row, i) => {
                const pkValues = extractPk(row);
                const key = primaryKey.length
                  ? primaryKey.map((p) => String(row[p] ?? "")).join("|") || `row-${i}`
                  : `row-${i}`;
                return (
                  <tr
                    key={key}
                    className="border-b border-border/30 hover:bg-muted/20"
                  >
                    {columns.map((c) => {
                      const isPk = pkSet.has(c.name);
                      const editable = !isPk && !!onCellEdit;
                      return (
                        <td
                          key={c.name}
                          className="align-top border-r border-border/20 last:border-r-0 p-0"
                        >
                          <EditableCell
                            value={row[c.name] ?? null}
                            column={c}
                            editable={editable}
                            onCommit={
                              editable && onCellEdit
                                ? (v) => onCellEdit(pkValues, c.name, v)
                                : undefined
                            }
                          />
                        </td>
                      );
                    })}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
