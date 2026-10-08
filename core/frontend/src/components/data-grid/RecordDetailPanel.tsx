import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Building2,
  Calendar,
  DollarSign,
  Hash,
  Key,
  Link2,
  type LucideIcon,
  Mail,
  Phone,
  ToggleLeft,
  Type,
  User,
  Loader2,
  Trash2,
  X,
} from "lucide-react";
import type { CellValue, ColumnInfo } from "@/api/colonyData";
import { globalDataApi, type ForeignKey } from "@/api/globalData";
import { displayValue, EditableCell } from "./EditableCell";
import {
  type ColumnOptions,
  extractPk,
  humanizeLabel,
  isSystemColumn,
  pkKey,
  type Row,
  titleColumn,
} from "./gridUtils";

interface RecordDetailPanelProps {
  table: string;
  columns: ColumnInfo[];
  primaryKey: string[];
  /** The record to show, keyed by its primary key. */
  row: Row;
  foreignKeys: ForeignKey[];
  /** Per-column display metadata for enumerable columns (e.g. status): drives
   *  colored bubbles and an enum picker instead of a free-text field. */
  columnOptions?: ColumnOptions;
  /** Render as an unsaved "new record" draft: fields edit locally and are only
   *  persisted via onCreate — no autosave, linked records, or delete. */
  isNew?: boolean;
  /** Persist the draft (create mode). Reject to surface a validation error
   *  inline while keeping the panel open. */
  onCreate?: (row: Row) => Promise<void>;
  onClose: () => void;
  /** Refresh the parent grid after an inline edit. */
  onEdited: () => void;
  /** Called after the record is deleted (parent closes + refreshes). */
  onDeleted: () => void;
}

/** A small leading icon for a field, chosen from the column's name/type so the
 *  panel reads like a form (mirrors the reference CRM's per-field icons). */
function fieldIcon(column: ColumnInfo, isPk: boolean): LucideIcon {
  if (isPk) return Key;
  const n = column.name.toLowerCase();
  const t = column.type.toUpperCase();
  if (n.includes("email")) return Mail;
  if (n.includes("phone") || n.includes("mobile") || n.includes("tel")) return Phone;
  if (/url|website|link|linkedin|github|twitter|site/.test(n)) return Link2;
  if (/revenue|amount|price|cost|mrr|arr|salary|budget|value|spend/.test(n)) return DollarSign;
  if (/_(at|date)$/.test(n) || n === "date" || t.includes("DATE") || t.includes("TIME")) {
    return Calendar;
  }
  if (/name|owner|contact|assignee|person|lead|author|user/.test(n)) return User;
  if (/company|account|organization|org|employer|team/.test(n)) return Building2;
  if (t.includes("BOOL")) return ToggleLeft;
  if (/INT|REAL|NUMERIC|FLOA|DOUB/.test(t)) return Hash;
  return Type;
}

interface LinkedSection {
  fk: ForeignKey;
  loading: boolean;
  rows: Row[];
  columns: ColumnInfo[];
  primaryKey: string[];
  error: string | null;
}

/** Slide-over for a single record: editable fields + a timeline of related
 *  child records discovered via foreign keys (e.g. a lead's interactions). */
export function RecordDetailPanel({
  table,
  columns,
  primaryKey,
  row,
  foreignKeys,
  columnOptions,
  isNew = false,
  onCreate,
  onClose,
  onEdited,
  onDeleted,
}: RecordDetailPanelProps) {
  const [local, setLocal] = useState<Row>(row);
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setLocal(row), [row]);

  const pkSet = useMemo(() => new Set(primaryKey), [primaryKey]);
  const title = useMemo(() => titleColumn(columns, primaryKey), [columns, primaryKey]);
  const pk = useMemo(() => extractPk(local, primaryKey), [local, primaryKey]);

  // On the draft form, hide the primary key (derived/minted on insert) and the
  // auto-stamped system columns — the user only fills the content fields.
  const visibleColumns = useMemo(
    () =>
      isNew
        ? columns.filter((c) => !pkSet.has(c.name) && !isSystemColumn(c.name))
        : columns,
    [isNew, columns, pkSet],
  );

  // Child tables whose FK points back at this table.
  const childRels = useMemo(
    () => foreignKeys.filter((fk) => fk.ref_table === table),
    [foreignKeys, table],
  );

  const [linked, setLinked] = useState<LinkedSection[]>([]);

  useEffect(() => {
    let cancelled = false;
    // A draft has no persisted key yet, so it has no child records to load.
    if (isNew || childRels.length === 0) {
      setLinked([]);
      return;
    }
    setLinked(
      childRels.map((fk) => ({
        fk,
        loading: true,
        rows: [],
        columns: [],
        primaryKey: [],
        error: null,
      })),
    );
    childRels.forEach((fk, i) => {
      const refValue = row[fk.ref_column];
      if (refValue == null) {
        setLinked((prev) =>
          prev.map((s, idx) => (idx === i ? { ...s, loading: false } : s)),
        );
        return;
      }
      globalDataApi
        .query(fk.table, {
          filter: [{ column: fk.column, op: "eq", value: refValue }],
          limit: 50,
        })
        .then((res) => {
          if (cancelled) return;
          setLinked((prev) =>
            prev.map((s, idx) =>
              idx === i
                ? {
                    ...s,
                    loading: false,
                    rows: res.rows,
                    columns: res.columns,
                    primaryKey: res.primary_key,
                  }
                : s,
            ),
          );
        })
        .catch((e: unknown) => {
          if (cancelled) return;
          setLinked((prev) =>
            prev.map((s, idx) =>
              idx === i
                ? { ...s, loading: false, error: (e as Error)?.message ?? "Failed to load" }
                : s,
            ),
          );
        });
    });
    return () => {
      cancelled = true;
    };
    // Re-run when the identity of the record changes.
  }, [isNew, childRels, row, pkKeyOf(pk, primaryKey)]);

  const commitField = useCallback(
    async (column: string, value: CellValue) => {
      // Draft mode: edits stay local until Create — no autosave round-trip.
      if (isNew) {
        setLocal((prev) => ({ ...prev, [column]: value }));
        return;
      }
      await globalDataApi.updateRow(table, { pk, updates: { [column]: value } });
      setLocal((prev) => ({ ...prev, [column]: value }));
      onEdited();
    },
    [isNew, table, pk, onEdited],
  );

  const handleCreate = useCallback(async () => {
    if (!onCreate) return;
    setCreating(true);
    setError(null);
    try {
      await onCreate(local);
      // On success the parent closes this panel; leave `creating` set so the
      // button stays disabled through unmount.
    } catch (e) {
      setError((e as Error)?.message ?? "Failed to create record");
      setCreating(false);
    }
  }, [onCreate, local]);

  const handleDelete = async () => {
    setDeleting(true);
    setError(null);
    try {
      await globalDataApi.deleteRow(table, pk);
      onDeleted();
    } catch (e) {
      setError((e as Error)?.message ?? "Failed to delete");
      setDeleting(false);
    }
  };

  return (
    <>
    <div className="fixed inset-0 z-40 flex justify-end">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative w-[620px] max-w-[94vw] h-full bg-card border-l border-border/60 shadow-2xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border/60">
          <div className="min-w-0">
            <div className="text-[10px] uppercase tracking-widest text-muted-foreground/50 mb-1">
              {table}
            </div>
            <div className="text-lg font-semibold text-foreground truncate leading-tight">
              {isNew ? "New record" : String(local[title] ?? "Untitled record")}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-md text-muted-foreground/50 hover:text-foreground hover:bg-muted/50"
            aria-label="Close"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {error && (
            <div className="m-3 px-3 py-2 rounded-md border border-destructive/30 bg-destructive/5 text-xs text-destructive">
              {error}
            </div>
          )}

          {/* Fields */}
          <div className="px-6 py-5 flex flex-col gap-2.5">
            {visibleColumns.map((c) => {
              const isPk = pkSet.has(c.name);
              const label = humanizeLabel(c.name);
              const Icon = fieldIcon(c, isPk);
              // Invite filling in empties on user-owned fields; system/pk columns
              // aren't hand-entered, so they keep the neutral dash.
              const placeholder =
                !isPk && !isSystemColumn(c.name) ? `Add ${label}` : undefined;
              return (
                <div key={c.name} className="grid grid-cols-[150px_1fr] gap-x-4 items-start">
                  <div
                    className="flex items-center gap-1.5 text-xs text-muted-foreground pt-2 min-w-0"
                    title={c.name}
                  >
                    <Icon className="w-3.5 h-3.5 shrink-0 text-muted-foreground/50" aria-hidden />
                    <span className="truncate">{label}</span>
                    {isPk && (
                      <span className="text-[9px] uppercase bg-primary/15 text-primary px-1 rounded shrink-0">
                        pk
                      </span>
                    )}
                  </div>
                  <div className="min-w-0 flex items-center rounded-md border border-border/40 bg-muted/10 overflow-hidden text-[13px] min-h-[34px]">
                    <EditableCell
                      value={local[c.name] ?? null}
                      column={c}
                      editable={!isPk}
                      onCommit={isPk ? undefined : (v) => commitField(c.name, v)}
                      options={columnOptions?.[c.name]}
                      placeholder={placeholder}
                    />
                  </div>
                </div>
              );
            })}
          </div>

          {/* Linked child records */}
          {!isNew && childRels.length > 0 && (
            <div className="px-6 py-5 border-t border-border/40 flex flex-col gap-4">
              {linked.map((sec) => (
                <div key={`${sec.fk.table}.${sec.fk.column}`}>
                  <div className="text-[11px] font-semibold text-foreground/70 mb-1.5 uppercase tracking-wide">
                    {sec.fk.table}{" "}
                    <span className="font-normal text-muted-foreground/50 normal-case tracking-normal">
                      via {sec.fk.column}
                    </span>
                    {!sec.loading && (
                      <span className="ml-1 text-[10px] tabular-nums text-muted-foreground/50">
                        ({sec.rows.length})
                      </span>
                    )}
                  </div>
                  {sec.loading ? (
                    <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
                  ) : sec.error ? (
                    <div className="text-xs text-destructive">{sec.error}</div>
                  ) : sec.rows.length === 0 ? (
                    <div className="text-xs text-muted-foreground/50">No related records.</div>
                  ) : (
                    <div className="flex flex-col gap-1.5">
                      {sec.rows.map((r, i) => (
                        <LinkedRecordRow
                          key={
                            sec.primaryKey.length
                              ? pkKey(extractPk(r, sec.primaryKey), sec.primaryKey)
                              : `r${i}`
                          }
                          row={r}
                          columns={sec.columns}
                          hideColumn={sec.fk.column}
                        />
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Footer: create (draft) or delete (existing record) */}
        <div className="px-6 py-3.5 border-t border-border/40 flex items-center justify-end gap-2">
          {isNew ? (
            <>
              <button
                onClick={onClose}
                disabled={creating}
                className="px-3 py-1.5 rounded-md text-xs text-muted-foreground hover:bg-muted/40 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleCreate}
                disabled={creating}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-md bg-primary text-primary-foreground text-xs font-medium hover:bg-primary/90 disabled:opacity-50"
              >
                {creating && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                Create
              </button>
            </>
          ) : (
            <button
              onClick={() => setConfirmDelete(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs text-destructive/70 hover:text-destructive hover:bg-destructive/10"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Delete record
            </button>
          )}
        </div>
      </div>
    </div>
      {confirmDelete && !isNew && (
        <DeleteConfirmDialog
          deleting={deleting}
          error={error}
          onCancel={() => {
            setConfirmDelete(false);
            setError(null);
          }}
          onConfirm={handleDelete}
        />
      )}
    </>
  );
}

/** Centered confirm popup for deleting a record — replaces an inline footer
 *  confirm so the destructive action reads as a deliberate modal choice. */
function DeleteConfirmDialog({
  deleting,
  error,
  onCancel,
  onConfirm,
}: {
  deleting: boolean;
  error: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !deleting) onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [deleting, onCancel]);

  return (
    <>
      <div
        className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
        onClick={deleting ? undefined : onCancel}
      />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-sm pointer-events-auto flex flex-col">
          <div className="flex items-start gap-3 px-5 pt-5">
            <div className="w-8 h-8 rounded-lg bg-destructive/10 border border-destructive/20 flex items-center justify-center flex-shrink-0">
              <Trash2 className="w-4 h-4 text-destructive" />
            </div>
            <div className="min-w-0">
              <h2 className="text-sm font-semibold text-foreground">Delete this record?</h2>
              <p className="text-[11px] text-muted-foreground mt-0.5">
                This permanently removes the record and can't be undone.
              </p>
            </div>
          </div>
          {error && (
            <div className="mx-5 mt-3 px-3 py-2 rounded-lg border border-destructive/20 bg-destructive/5 text-[11px] text-destructive">
              {error}
            </div>
          )}
          <div className="flex items-center justify-end gap-2 px-5 py-4">
            <button
              onClick={onCancel}
              disabled={deleting}
              className="px-3 py-1.5 rounded-md text-xs font-medium border border-border/60 text-muted-foreground hover:bg-muted/40 disabled:opacity-40"
            >
              Cancel
            </button>
            <button
              onClick={onConfirm}
              disabled={deleting}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold bg-destructive text-destructive-foreground hover:bg-destructive/90 disabled:opacity-40"
            >
              {deleting ? (
                <Loader2 className="w-3 h-3 animate-spin" />
              ) : (
                <Trash2 className="w-3 h-3" />
              )}
              Delete
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

/** Compact one-line summary of a linked record: a couple of meaningful fields. */
function LinkedRecordRow({
  row,
  columns,
  hideColumn,
}: {
  row: Row;
  columns: ColumnInfo[];
  hideColumn: string;
}) {
  const shown = columns
    .filter((c) => c.name !== hideColumn && c.pk === 0)
    .filter((c) => row[c.name] != null && row[c.name] !== "")
    .slice(0, 3);
  return (
    <div className="rounded-md border border-border/30 bg-muted/10 px-2.5 py-1.5 text-xs">
      {shown.length === 0 ? (
        <span className="text-muted-foreground/40">(empty)</span>
      ) : (
        shown.map((c, i) => (
          <span key={c.name} className="text-foreground/70">
            {i > 0 && <span className="text-muted-foreground/25"> · </span>}
            <span className="text-muted-foreground/40">{c.name}:</span>{" "}
            {displayValue(row[c.name], c)}
          </span>
        ))
      )}
    </div>
  );
}

/** Local helper so the effect dep list can key on PK identity. */
function pkKeyOf(pk: Row, primaryKey: string[]): string {
  return pkKey(pk, primaryKey);
}
