import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import type { CellValue, ColumnInfo } from "@/api/colonyData";

interface EditableCellProps {
  value: CellValue;
  column: ColumnInfo;
  editable: boolean;
  onCommit?: (newValue: CellValue) => Promise<void>;
}

/** Parse a textarea draft back to the typed column value. Empty input
 *  maps to NULL when the column is nullable; otherwise empty-string.
 *  Invalid numerics throw — caller surfaces as a cell error. */
function parseDraft(draft: string, column: ColumnInfo): CellValue {
  const t = column.type.toUpperCase();
  const trimmed = draft.trim();
  if (trimmed === "") return column.notnull ? "" : null;

  if (t.includes("INT")) {
    const n = Number(trimmed);
    if (!Number.isFinite(n) || !Number.isInteger(n)) {
      throw new Error(`${column.name} expects an integer`);
    }
    return n;
  }
  if (t.includes("REAL") || t.includes("FLOA") || t.includes("DOUB") || t.includes("NUMERIC")) {
    const n = Number(trimmed);
    if (!Number.isFinite(n)) throw new Error(`${column.name} expects a number`);
    return n;
  }
  if (t.includes("BOOL")) {
    const lower = trimmed.toLowerCase();
    if (lower === "true" || lower === "1") return true;
    if (lower === "false" || lower === "0") return false;
    throw new Error(`${column.name} expects true/false`);
  }
  // TEXT / unknown affinity — keep as-is.
  return draft;
}

function formatValue(v: CellValue): string {
  if (v == null) return "";
  if (typeof v === "boolean") return v ? "true" : "false";
  return String(v);
}

export function EditableCell({ value, column, editable, onCommit }: EditableCellProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string>(formatValue(value));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  // Reset local draft whenever the upstream value changes (e.g. after
  // a row refresh). Skipping this leaves stale drafts visible.
  useEffect(() => {
    if (!editing) setDraft(formatValue(value));
  }, [value, editing]);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  const startEdit = () => {
    if (!editable || saving) return;
    setError(null);
    setDraft(formatValue(value));
    setEditing(true);
  };

  const cancel = () => {
    setEditing(false);
    setError(null);
    setDraft(formatValue(value));
  };

  const commit = async () => {
    if (!onCommit) {
      setEditing(false);
      return;
    }
    let parsed: CellValue;
    try {
      parsed = parseDraft(draft, column);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return;
    }
    // No-op if value didn't change.
    if (parsed === value || (parsed === "" && value == null)) {
      setEditing(false);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await onCommit(parsed);
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const display = formatValue(value);
  const isNull = value === null;

  if (editing) {
    return (
      <div className="relative">
        <textarea
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.preventDefault();
              cancel();
            } else if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              commit();
            }
          }}
          rows={1}
          className="w-full min-w-[120px] bg-background text-foreground text-[11px] font-mono border-2 border-primary/60 outline-none px-1.5 py-1 resize-none"
          disabled={saving}
        />
        {saving && (
          <span className="absolute right-1 top-1 text-muted-foreground">
            <Loader2 className="w-3 h-3 animate-spin" />
          </span>
        )}
        {error && (
          <div className="absolute z-20 top-full left-0 mt-0.5 bg-destructive text-destructive-foreground text-[10px] px-1.5 py-0.5 rounded whitespace-nowrap max-w-[300px] truncate shadow-lg">
            {error}
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      onClick={startEdit}
      onDoubleClick={startEdit}
      className={`min-w-[80px] max-w-[280px] px-1.5 py-1 font-mono truncate ${
        editable ? "cursor-text hover:bg-muted/40" : "cursor-default"
      } ${isNull ? "text-muted-foreground/60 italic" : "text-foreground/90"}`}
      title={isNull ? "NULL" : display}
    >
      {isNull ? "NULL" : display || "\u00A0"}
    </div>
  );
}
