import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, Loader2 } from "lucide-react";
import type { CellValue, ColumnInfo } from "@/api/colonyData";
import { type ColumnOption, findOption, optionLabel } from "./gridUtils";

interface EditableCellProps {
  value: CellValue;
  column: ColumnInfo;
  editable: boolean;
  onCommit?: (newValue: CellValue) => Promise<void>;
  /** When the column is enumerable (e.g. status), the ordered options with
   *  colors — renders the value as a colored bubble instead of plain text. */
  options?: ColumnOption[];
  /** When false, `options` only drive the colored bubbles — editing keeps the
   *  free-text box instead of the restricted picker. For inferred (page-local)
   *  options, where an unseen value must stay enterable. Default true. */
  optionsEditable?: boolean;
  /** Numeric column: right-align with tabular figures, and mute zeros so
   *  nonzero values stand out. */
  numeric?: boolean;
  /** Text shown (muted) in place of the "—" dash when the value is empty —
   *  e.g. "Add email" in the detail panel. Omitted in the dense grid, which
   *  keeps the bare dash. */
  placeholder?: string;
}

/** Values that read better with a middle ellipsis: ids, hashes, URLs — where
 *  the distinguishing part is the tail. Heuristic: a single long token with no
 *  whitespace. Prose (which has spaces) keeps a normal end ellipsis. */
function isIdLike(s: string): boolean {
  return s.length > 24 && !/\s/.test(s);
}

/** A plain http(s) URL — rendered as a link that opens in the OS browser. */
function isUrl(s: string): boolean {
  return /^https?:\/\/\S+$/i.test(s);
}

/** Display form of a URL: the scheme carries no information in a grid cell,
 *  so it's stripped (the full URL stays in the tooltip and the link target). */
function urlDisplayText(url: string): string {
  return url.replace(/^https?:\/\//i, "");
}

/** Pure-CSS middle truncation: the head shrinks + ellipsizes while a fixed
 *  tail stays pinned, so "https://…/abc123" keeps both ends visible. Collapses
 *  back to the full string whenever the column is wide enough to fit it. */
function MiddleTruncate({ text }: { text: string }) {
  const tailLen = Math.min(8, Math.floor(text.length / 2));
  const head = text.slice(0, text.length - tailLen);
  const tail = text.slice(text.length - tailLen);
  return (
    <span className="flex w-full min-w-0">
      <span className="truncate">{head}</span>
      <span className="shrink-0 whitespace-pre">{tail}</span>
    </span>
  );
}

/** A pill rendering an enumerable value (status, etc.) in its lookup color.
 *  Color is a hex string; the bubble derives a translucent fill + border from
 *  it so it reads in both themes. Exported for group/board headers. */
export function ValueBadge({ label, color }: { label: string; color?: string | null }) {
  const c = color || "#64748b";
  return (
    <span
      className="inline-flex items-center max-w-full truncate rounded-full border px-2 py-0.5 text-[10px] font-medium leading-tight"
      style={{ color: c, backgroundColor: `${c}1f`, borderColor: `${c}59` }}
    >
      {label}
    </span>
  );
}

/** A column that stores a CSS hex color (e.g. the `color` column of a
 *  lead_status lookup) — rendered as a swatch + hex and edited with a color
 *  picker instead of a text box. Gated on the column NAME so no other column
 *  pays for the value check; this keeps large, unrelated tables untouched. */
function isColorColumn(column: ColumnInfo): boolean {
  return column.name === "color" || /_colou?r$/.test(column.name);
}

/** A 3- or 6-digit CSS hex string like `#22c55e`. */
function isHexColor(s: string): boolean {
  return /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i.test(s);
}

/** Normalize to the `#rrggbb` form the native <input type="color"> requires;
 *  falls back to a neutral gray for empty/invalid values. */
function toPickerHex(s: string): string {
  const short = /^#([0-9a-f]{3})$/i.exec(s);
  if (short) {
    const [r, g, b] = short[1].split("");
    return `#${r}${r}${g}${g}${b}${b}`.toLowerCase();
  }
  return /^#[0-9a-f]{6}$/i.test(s) ? s.toLowerCase() : "#64748b";
}

/** A common palette shown as one-click chips in the color editor, so a
 *  non-technical user rarely needs to open the full picker or type a hex. */
const PRESET_COLORS = [
  "#ef4444", "#f97316", "#f59e0b", "#eab308", "#22c55e",
  "#10b981", "#06b6d4", "#3b82f6", "#6366f1", "#8b5cf6",
  "#ec4899", "#64748b",
];

/** Swatch + hex for a color cell — a filled chip so a non-technical user can
 *  see the color at a glance, with the hex kept alongside for reference. */
function ColorSwatch({ hex }: { hex: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 max-w-full">
      <span
        className="inline-block h-3.5 w-3.5 flex-shrink-0 rounded border border-border/60"
        style={{ backgroundColor: hex }}
      />
      <span className="truncate">{hex}</span>
    </span>
  );
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

/** A resolved foreign-key value projected by the CRM read layer: the label is
 *  shown, the id carried for navigation. Rendered as its label, never a UUID. */
function refLabel(v: unknown): string | null {
  if (v && typeof v === "object" && !Array.isArray(v)) {
    const o = v as Record<string, unknown>;
    if (typeof o.label === "string") return o.label;
    if (typeof o.name === "string") return o.name;
  }
  return null;
}

/** Human text for ANY value — including the objects/arrays the CRM projection
 *  can produce (resolved FK refs, custom text[] fields) and any stray JSONB.
 *  The one guarantee: never "[object Object]". */
function humanText(v: unknown): string {
  if (v == null) return "";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "object") {
    const label = refLabel(v);
    if (label != null) return label;
    if (Array.isArray(v)) return v.map((x) => (x == null ? "" : String(x))).join(", ");
    try {
      return JSON.stringify(v);
    } catch {
      return "";
    }
  }
  return String(v);
}

/** Raw editable text for a value — used to seed the edit draft and to parse
 *  back. Stays verbatim so edits round-trip losslessly. */
function formatValue(v: CellValue): string {
  return humanText(v);
}

// Framework-managed timestamps — read-only in the grid (not hand-edited).
const SYSTEM_TIMESTAMPS = new Set(["created_at", "updated_at"]);

/** A column that holds a date/time, by SQL type or ``*_at`` / ``*_date`` name. */
function isTemporal(column: ColumnInfo): boolean {
  const t = column.type.toLowerCase();
  if (t.includes("timestamp") || t.includes("date") || t.includes("time")) return true;
  return /_(at|date)$/.test(column.name) || column.name === "date";
}

/** Coerce ISO strings or epoch numbers to a Date; null if not a valid date. */
function toDate(v: CellValue): Date | null {
  if (typeof v === "number") {
    const ms = v < 1e12 ? v * 1000 : v; // epoch seconds vs milliseconds
    const d = new Date(ms);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  if (typeof v === "string" && v.trim() !== "") {
    const d = new Date(v);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  return null;
}

const ABS_FMT: Intl.DateTimeFormatOptions = {
  month: "short",
  day: "numeric",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
};

/** Human-facing display: absolute, localized timestamps for temporal columns
 *  (e.g. "Jun 19, 2026, 11:44 AM"); verbatim otherwise. Exported so the
 *  Kanban cards and record detail panel render values identically. */
export function displayValue(v: CellValue, column: ColumnInfo): string {
  if (v == null) return "";
  if (typeof v === "boolean") return v ? "true" : "false";
  // Resolved FK refs, custom arrays, or any object slipping through (metadata)
  // render as human text — never "[object Object]".
  if (typeof v === "object") return humanText(v);
  if (isTemporal(column)) {
    const d = toDate(v);
    if (d) return d.toLocaleString(undefined, ABS_FMT);
  }
  return String(v);
}

/** Exact local datetime (with timezone) for the hover tooltip. */
function preciseTimestamp(v: CellValue): string | null {
  const d = toDate(v);
  return d ? d.toLocaleString(undefined, { dateStyle: "full", timeStyle: "long" }) : null;
}

export function EditableCell({
  value,
  column,
  editable,
  onCommit,
  options,
  optionsEditable = true,
  numeric = false,
  placeholder,
}: EditableCellProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string>(formatValue(value));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  // Pending single-click "open URL" action, deferred so a double-click (to
  // edit) can cancel it before the browser launches.
  const openTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => {
    if (openTimer.current) clearTimeout(openTimer.current);
  }, []);

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

  // Framework-managed timestamps (created_at/updated_at) are display-only.
  const isEditable =
    editable && !(isTemporal(column) && SYSTEM_TIMESTAMPS.has(column.name));
  // Enumerable column (has a fixed option set, e.g. status) → edit via a
  // picker of the allowed values instead of a free-text box, so an invalid
  // value can't be entered (and can't trip a DB constraint) in the first place.
  const enumEditable = isEditable && optionsEditable && !!options && options.length > 0;
  // Color column (e.g. lead_status.color) → edit via a swatch/preset picker
  // instead of a free-text hex box.
  const colorEditable = isEditable && isColorColumn(column);

  const startEdit = () => {
    if (!isEditable || saving) return;
    setError(null);
    setDraft(formatValue(value));
    setEditing(true);
  };

  const cancel = () => {
    setEditing(false);
    setError(null);
    setDraft(formatValue(value));
  };

  // Push a fully-typed value to the server. A rejection (e.g. a status the DB
  // constrains) surfaces inline and keeps the cell in edit mode — the row's
  // committed value is never touched, so a bad edit can't corrupt the screen.
  const commitValue = async (parsed: CellValue) => {
    if (!onCommit) {
      setEditing(false);
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

  const commit = async () => {
    let parsed: CellValue;
    try {
      parsed = parseDraft(draft, column);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return;
    }
    await commitValue(parsed);
  };

  const display = displayValue(value, column);
  const isNull = value === null;
  // Enumerable value (status, etc.) → render as a colored bubble.
  const option = findOption(options, value);
  // Long opaque tokens (ids/urls) get a middle ellipsis so the tail stays
  // visible; everything else keeps the plain end-ellipsis truncate.
  const showMiddle = !isNull && !option && isIdLike(display);
  // Hex-valued color column → render a swatch. Name check first, so unrelated
  // columns skip the hex regex entirely.
  const colorHex =
    !isNull && !option && isColorColumn(column) && isHexColor(display) ? display : null;
  // http(s) values render as a link that opens in the OS browser.
  const url = !isNull && !option && !colorHex && isUrl(display) ? display : null;
  // Tooltip: exact local datetime for timestamps, else the full value.
  const tooltip = isTemporal(column) ? preciseTimestamp(value) ?? display : display;

  if (editing && colorEditable) {
    return (
      <ColorEditPopover
        value={value}
        nullable={!column.notnull}
        saving={saving}
        error={error}
        onSelect={commitValue}
        onCancel={cancel}
      />
    );
  }

  if (editing && enumEditable) {
    return (
      <EnumEditPopover
        options={options!}
        value={value}
        nullable={!column.notnull}
        saving={saving}
        error={error}
        onSelect={commitValue}
        onCancel={cancel}
      />
    );
  }

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
      className={`min-w-0 w-full px-1.5 py-1 ${url || showMiddle ? "" : "truncate"} ${
        option ? "" : "font-mono"
      } ${numeric ? "text-right tabular-nums" : ""} ${
        isEditable ? "cursor-text hover:bg-muted/40" : "cursor-default"
      } ${
        isNull || (numeric && (value === 0 || value === "0"))
          ? "text-muted-foreground/40"
          : "text-foreground/90"
      }`}
      title={isNull ? "" : tooltip}
    >
      {isNull ? (
        placeholder ?? "\u2014"
      ) : option ? (
        <ValueBadge label={optionLabel(option, value)} color={option.color} />
      ) : colorHex ? (
        <ColorSwatch hex={colorHex} />
      ) : url ? (
        <a
          href={url}
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            // Second click of a double-click: let onDoubleClick cancel + edit.
            if (openTimer.current) return;
            openTimer.current = setTimeout(() => {
              openTimer.current = null;
              window.open(url, "_blank", "noopener");
            }, 200);
          }}
          onDoubleClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            if (openTimer.current) {
              clearTimeout(openTimer.current);
              openTimer.current = null;
            }
            startEdit();
          }}
          className="block w-full min-w-0 max-w-[220px] cursor-pointer text-primary no-underline underline-offset-2 decoration-primary/60 hover:underline"
        >
          <MiddleTruncate text={urlDisplayText(url)} />
        </a>
      ) : showMiddle ? (
        <MiddleTruncate text={display} />
      ) : (
        display || "\u00A0"
      )}
    </div>
  );
}

/** Picker shown while editing an enumerable cell: the allowed values as colored
 *  bubbles. Selecting one commits it; outside-click / Escape / scroll cancels.
 *  The menu is portaled to <body> and fixed-positioned off the cell's rect so
 *  it escapes the grid's / detail panel's overflow-clipping ancestors. Only
 *  listed values are selectable, so the edit can't produce a value the DB
 *  rejects. */
function EnumEditPopover({
  options,
  value,
  nullable,
  saving,
  error,
  onSelect,
  onCancel,
}: {
  options: ColumnOption[];
  value: CellValue;
  nullable: boolean;
  saving: boolean;
  error: string | null;
  onSelect: (v: CellValue) => void;
  onCancel: () => void;
}) {
  const anchorRef = useRef<HTMLDivElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [rect, setRect] = useState<DOMRect | null>(null);

  useLayoutEffect(() => {
    if (anchorRef.current) setRect(anchorRef.current.getBoundingClientRect());
  }, []);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (menuRef.current?.contains(t) || anchorRef.current?.contains(t)) return;
      onCancel();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    // A scroll/resize moves the anchor out from under the fixed menu; close
    // rather than let it float detached.
    document.addEventListener("mousedown", onDown, true);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onCancel, true);
    window.addEventListener("resize", onCancel);
    return () => {
      document.removeEventListener("mousedown", onDown, true);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onCancel, true);
      window.removeEventListener("resize", onCancel);
    };
  }, [onCancel]);

  const cur = value == null ? "" : String(value);

  // Position below the cell, flipping above when there isn't room; clamp to the
  // viewport so a right-edge column doesn't overflow off-screen.
  const MENU_MAX = 264;
  const style: React.CSSProperties | null = rect
    ? (() => {
        const openUp =
          rect.bottom + MENU_MAX > window.innerHeight && rect.top > window.innerHeight - rect.bottom;
        const left = Math.max(8, Math.min(rect.left, window.innerWidth - 260));
        return openUp
          ? { position: "fixed", bottom: window.innerHeight - rect.top + 4, left, minWidth: rect.width }
          : { position: "fixed", top: rect.bottom + 4, left, minWidth: rect.width };
      })()
    : null;

  return (
    <div ref={anchorRef} className="flex min-h-[24px] items-center px-1.5 py-1">
      {cur ? (
        <ValueBadge
          label={optionLabel(findOption(options, value), value)}
          color={findOption(options, value)?.color}
        />
      ) : (
        <span className="text-[10px] text-muted-foreground/60">Select…</span>
      )}
      {saving && <Loader2 className="ml-1 h-3 w-3 animate-spin text-muted-foreground" />}
      {style &&
        createPortal(
          <div
            ref={menuRef}
            style={style}
            className="z-[100] max-h-60 w-max min-w-[150px] max-w-[260px] overflow-y-auto rounded-lg border border-border/60 bg-card p-1 shadow-xl"
          >
            {options.map((o) => (
              <button
                key={o.value}
                type="button"
                disabled={saving}
                onClick={() => onSelect(o.value)}
                className={`flex w-full items-center justify-between gap-2 rounded-md px-1.5 py-1 text-left transition-colors hover:bg-muted/50 disabled:opacity-50 ${
                  o.value === cur ? "bg-primary/5" : ""
                }`}
              >
                <ValueBadge label={optionLabel(o, o.value)} color={o.color} />
                {o.value === cur && <Check className="h-3.5 w-3.5 flex-shrink-0 text-primary" />}
              </button>
            ))}
            {nullable && (
              <button
                type="button"
                disabled={saving}
                onClick={() => onSelect(null)}
                className="w-full rounded-md px-2 py-1 text-left text-[11px] text-muted-foreground hover:bg-muted/50 disabled:opacity-50"
              >
                Clear
              </button>
            )}
            {error && (
              <div className="mt-0.5 max-w-[240px] rounded bg-destructive px-1.5 py-0.5 text-[10px] text-destructive-foreground">
                {error}
              </div>
            )}
          </div>,
          document.body,
        )}
    </div>
  );
}

/** Picker shown while editing a color cell: preset chips + the OS-native color
 *  picker, so a non-technical user can pick a color without typing a hex.
 *  Portaled/positioned/closed exactly like {@link EnumEditPopover}. Selecting a
 *  preset or confirming the native picker commits the `#rrggbb` value. */
function ColorEditPopover({
  value,
  nullable,
  saving,
  error,
  onSelect,
  onCancel,
}: {
  value: CellValue;
  nullable: boolean;
  saving: boolean;
  error: string | null;
  onSelect: (v: CellValue) => void;
  onCancel: () => void;
}) {
  const anchorRef = useRef<HTMLDivElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [rect, setRect] = useState<DOMRect | null>(null);

  useLayoutEffect(() => {
    if (anchorRef.current) setRect(anchorRef.current.getBoundingClientRect());
  }, []);

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (menuRef.current?.contains(t) || anchorRef.current?.contains(t)) return;
      onCancel();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    document.addEventListener("mousedown", onDown, true);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onCancel, true);
    window.addEventListener("resize", onCancel);
    return () => {
      document.removeEventListener("mousedown", onDown, true);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onCancel, true);
      window.removeEventListener("resize", onCancel);
    };
  }, [onCancel]);

  const cur = value == null ? "" : String(value);
  const pickerHex = toPickerHex(cur);

  const MENU_MAX = 220;
  const style: React.CSSProperties | null = rect
    ? (() => {
        const openUp =
          rect.bottom + MENU_MAX > window.innerHeight && rect.top > window.innerHeight - rect.bottom;
        const left = Math.max(8, Math.min(rect.left, window.innerWidth - 260));
        return openUp
          ? { position: "fixed", bottom: window.innerHeight - rect.top + 4, left, minWidth: rect.width }
          : { position: "fixed", top: rect.bottom + 4, left, minWidth: rect.width };
      })()
    : null;

  return (
    <div ref={anchorRef} className="flex min-h-[24px] items-center px-1.5 py-1">
      {isHexColor(cur) ? (
        <ColorSwatch hex={cur} />
      ) : (
        <span className="text-[10px] text-muted-foreground/60">Pick a color…</span>
      )}
      {saving && <Loader2 className="ml-1 h-3 w-3 animate-spin text-muted-foreground" />}
      {style &&
        createPortal(
          <div
            ref={menuRef}
            style={style}
            className="z-[100] w-max min-w-[180px] rounded-lg border border-border/60 bg-card p-2 shadow-xl"
          >
            {/* Preset chips — one click commits, the common path for a
                non-technical user. */}
            <div className="grid grid-cols-6 gap-1.5">
              {PRESET_COLORS.map((c) => (
                <button
                  key={c}
                  type="button"
                  disabled={saving}
                  title={c}
                  onClick={() => onSelect(c)}
                  className={`h-5 w-5 rounded border transition-transform hover:scale-110 disabled:opacity-50 ${
                    c.toLowerCase() === cur.toLowerCase() ? "border-foreground" : "border-border/60"
                  }`}
                  style={{ backgroundColor: c }}
                />
              ))}
            </div>
            {/* OS-native picker for any exact color — commits on confirm. */}
            <label className="mt-2 flex cursor-pointer items-center gap-2 rounded-md px-1 py-1 text-[11px] text-muted-foreground hover:bg-muted/50">
              <input
                type="color"
                defaultValue={pickerHex}
                disabled={saving}
                onChange={(e) => onSelect(e.target.value)}
                className="h-5 w-8 cursor-pointer rounded border border-border/60 bg-transparent p-0"
              />
              Custom…
            </label>
            {nullable && (
              <button
                type="button"
                disabled={saving}
                onClick={() => onSelect(null)}
                className="mt-1 w-full rounded-md px-2 py-1 text-left text-[11px] text-muted-foreground hover:bg-muted/50 disabled:opacity-50"
              >
                Clear
              </button>
            )}
            {error && (
              <div className="mt-1 max-w-[240px] rounded bg-destructive px-1.5 py-0.5 text-[10px] text-destructive-foreground">
                {error}
              </div>
            )}
          </div>,
          document.body,
        )}
    </div>
  );
}
