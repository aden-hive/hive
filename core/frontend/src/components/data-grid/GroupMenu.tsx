import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Group as GroupIcon, X } from "lucide-react";
import { humanizeLabel } from "./gridUtils";

interface GroupMenuProps {
  /** Currently grouped field, or null when ungrouped. */
  value: string | null;
  options: string[];
  onChange: (value: string | null) => void;
  /** Whether to offer a "No grouping" entry (table view yes, Kanban no). */
  allowNone?: boolean;
}

/** Styled group-by control: a pill button that reflects the active field, with
 *  a popover list of groupable columns. Replaces the bare native <select>. */
export function GroupMenu({ value, options, onChange, allowNone = true }: GroupMenuProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const active = value != null;
  const choose = (v: string | null) => {
    onChange(v);
    setOpen(false);
  };

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((o) => !o)}
        title="Group by"
        className={`flex items-center gap-1.5 h-9 px-2.5 rounded-lg border text-xs font-medium transition-colors ${
          active
            ? "border-primary/40 bg-primary/10 text-primary"
            : "border-border/60 text-muted-foreground hover:text-foreground hover:bg-muted/30"
        }`}
      >
        <GroupIcon className="w-3.5 h-3.5" />
        <span className="max-w-[120px] truncate">
          {active ? (
            <>
              <span className="opacity-60">Group:</span> {humanizeLabel(value!)}
            </>
          ) : (
            "Group"
          )}
        </span>
        <ChevronDown
          className={`w-3 h-3 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1.5 z-30 w-52 rounded-lg border border-border/60 bg-card shadow-xl p-1">
          <div className="px-2 py-1 text-[10px] uppercase tracking-wider text-muted-foreground/60">
            Group rows by
          </div>
          {allowNone && (
            <MenuItem
              label="No grouping"
              icon={<X className="w-3.5 h-3.5" />}
              selected={value == null}
              onClick={() => choose(null)}
            />
          )}
          {options.map((o) => (
            <MenuItem
              key={o}
              label={humanizeLabel(o)}
              selected={value === o}
              onClick={() => choose(o)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function MenuItem({
  label,
  selected,
  onClick,
  icon,
}: {
  label: string;
  selected: boolean;
  onClick: () => void;
  icon?: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded-md text-[11px] transition-colors ${
        selected
          ? "bg-primary/10 text-primary font-medium"
          : "text-foreground/80 hover:bg-muted/50"
      }`}
    >
      <span className="flex items-center gap-1.5 min-w-0">
        {icon && <span className="text-muted-foreground/50">{icon}</span>}
        <span className="truncate">{label}</span>
      </span>
      {selected && <Check className="w-3.5 h-3.5 flex-shrink-0" />}
    </button>
  );
}
