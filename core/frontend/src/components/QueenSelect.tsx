/**
 * Shared queen picker — one themed dropdown used everywhere a queen is chosen
 * (Skills page context switcher, Skills upload modal, Tools page). Shows the
 * queen's ROLE first (e.g. "Queen of Growth"), persona name secondary.
 *
 *   <QueenSelect queens={queens} value={id} onChange={setId} />
 *   <QueenSelect ... allowAll meta={(id) => `${counts.get(id) ?? 0} skills`} />
 */
import { useMemo, useState, type ReactNode } from "react";
import { Crown, ChevronDown } from "lucide-react";

export interface QueenOption {
  id: string;
  name: string;
  title?: string;
}

/**
 * Render a queen's title as her role. Titles ship as "Head of Growth"; the
 * surfaces that show this already say "queen" (crown icon, queen picker), so
 * the label is just the domain — "Growth". Titles that don't match the
 * "Head of …" shape are shown verbatim.
 */
export function queenRoleLabel(title?: string): string | null {
  const t = (title ?? "").trim();
  if (!t) return null;
  const m = t.match(/^head of\s+(.*)$/i);
  return m ? m[1] : t;
}

/** The single-line label for a queen: role if present, else persona name. */
export function queenLabel(q: QueenOption): string {
  return queenRoleLabel(q.title) ?? q.name;
}

export function QueenSelect({
  queens,
  value,
  onChange,
  allowAll = false,
  allLabel = "All queens",
  allMeta,
  meta,
  prefix,
  placeholder = "Select a queen",
  buttonClassName = "",
}: {
  queens: QueenOption[];
  value: string | null;
  onChange: (id: string | null) => void;
  /** Show an "All queens" entry that maps to null. */
  allowAll?: boolean;
  allLabel?: string;
  /** Trailing meta for the "All queens" row (e.g. "browse"). */
  allMeta?: ReactNode;
  /** Trailing meta per queen (e.g. skill counts). */
  meta?: (id: string) => ReactNode;
  /** Muted prefix inside the trigger, e.g. "Configuring:". */
  prefix?: string;
  /** Trigger text when nothing is selected and allowAll is false. */
  placeholder?: string;
  /** Extra classes for the trigger button (width, etc.). */
  buttonClassName?: string;
}) {
  const [open, setOpen] = useState(false);
  const [filter, setFilter] = useState("");
  const selected = queens.find((q) => q.id === value) ?? null;

  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return queens;
    return queens.filter(
      (x) =>
        x.name.toLowerCase().includes(q) || (x.title ?? "").toLowerCase().includes(q),
    );
  }, [queens, filter]);

  const triggerText = selected ? queenLabel(selected) : allowAll ? allLabel : placeholder;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={`flex items-center gap-2 px-3 py-2 rounded-lg border border-border/60 bg-card text-sm font-medium text-foreground hover:border-primary/40 focus:outline-none focus:ring-1 focus:ring-primary/40 ${buttonClassName}`}
      >
        <Crown className="w-3.5 h-3.5 text-primary flex-shrink-0" />
        {prefix && <span className="text-muted-foreground font-normal">{prefix}</span>}
        <span className={`min-w-0 flex-1 truncate text-left ${selected || allowAll ? "" : "text-muted-foreground"}`}>
          {triggerText}
        </span>
        <ChevronDown className="w-4 h-4 text-muted-foreground flex-shrink-0" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-[60]" onClick={() => setOpen(false)} />
          <div className="absolute left-0 z-[61] mt-1 min-w-full w-72 max-w-[calc(100vw-2rem)] rounded-lg border border-border/60 bg-card shadow-lg p-1 max-h-[60vh] overflow-y-auto">
            {queens.length > 8 && (
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                autoFocus
                placeholder="Filter queens…"
                className="w-full mb-1 px-2.5 py-1.5 rounded-md bg-muted/30 border border-border/40 text-xs focus:outline-none focus:border-primary/50"
              />
            )}
            {allowAll && (
              <button
                type="button"
                onClick={() => {
                  onChange(null);
                  setOpen(false);
                }}
                className={`w-full flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-md text-sm hover:bg-muted/60 ${
                  value === null ? "text-primary font-medium" : "text-foreground"
                }`}
              >
                <span className="truncate">{allLabel}</span>
                {allMeta != null && (
                  <span className="text-[10px] text-muted-foreground flex-shrink-0">{allMeta}</span>
                )}
              </button>
            )}
            {shown.map((q) => {
              const role = queenRoleLabel(q.title);
              return (
                <button
                  key={q.id}
                  type="button"
                  onClick={() => {
                    onChange(q.id);
                    setOpen(false);
                  }}
                  className={`w-full flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-md text-sm hover:bg-muted/60 ${
                    value === q.id ? "text-primary" : "text-foreground"
                  }`}
                >
                  <span className="min-w-0 flex flex-col items-start">
                    <span className="truncate max-w-[180px] font-medium">{role ?? q.name}</span>
                    {role && (
                      <span className="truncate max-w-[180px] text-[10px] text-muted-foreground">
                        {q.name}
                      </span>
                    )}
                  </span>
                  {meta && (
                    <span className="text-[10px] text-muted-foreground flex-shrink-0">
                      {meta(q.id)}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
