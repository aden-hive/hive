import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Check, ChevronDown } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export interface MenuOption {
  value: string;
  label: string;
  /** Optional glyph shown before the label, in the trigger and the list. Lets a
   *  picker carry its own iconography instead of the caller parking a separate
   *  icon tile next to the control. */
  icon?: LucideIcon;
  /** Optional CSS color shown as a filled dot before the label. For vocabularies
   *  that are already color-coded elsewhere — kanban stages — so the picker
   *  speaks the same color the badge and the board column do. */
  dot?: string | null;
}

interface MenuSelectProps {
  value: string;
  options: MenuOption[];
  onChange: (value: string) => void;
  /** Width/spacing classes for the trigger button. */
  className?: string;
  /** Extra classes merged into the trigger itself (height, type scale), for a
   *  caller whose surrounding controls aren't the default compact size. */
  triggerClassName?: string;
  /** Popover alignment relative to the trigger. */
  align?: "left" | "right";
  ariaLabel?: string;
}

/** How tall the popover may get — also the budget used to decide whether it
 *  opens downward or flips up. */
const MENU_MAX = 240;

/** An option's color chip. A ring rather than a bare disc so a pale stage color
 *  still reads against the trigger's background. */
function Dot({ color }: { color: string }) {
  return (
    <span
      aria-hidden
      className="h-2 w-2 flex-shrink-0 rounded-full"
      style={{ backgroundColor: color, boxShadow: `0 0 0 2px ${color}33` }}
    />
  );
}

/** Compact, styled replacement for a native <select>: a bordered trigger that
 *  shows the current label, and a popover list with a checkmark on the active
 *  option. Closes on outside-click / Escape.
 *
 *  The popover renders in a PORTAL with fixed positioning rather than as an
 *  absolutely-positioned child. An absolute popover is clipped by any ancestor
 *  with `overflow` — a scrolling panel, a rounded card — which makes the control
 *  silently do nothing: the menu opens, into a region nobody can see. Portalling
 *  it means the same component works wherever it's dropped, and it can flip up
 *  when it would otherwise run off the bottom of the window. */
export function MenuSelect({
  value,
  options,
  onChange,
  className = "",
  triggerClassName,
  align = "left",
  ariaLabel,
}: MenuSelectProps) {
  const [open, setOpen] = useState(false);
  const [rect, setRect] = useState<DOMRect | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  // Measure before paint so the menu never renders at a stale position.
  useLayoutEffect(() => {
    if (!open) return setRect(null);
    setRect(triggerRef.current?.getBoundingClientRect() ?? null);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      // The menu lives outside the trigger's DOM subtree now, so an
      // outside-click check has to consider both.
      if (triggerRef.current?.contains(t) || menuRef.current?.contains(t)) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    // Fixed positioning doesn't follow a scrolling ancestor, so close instead of
    // letting the menu drift away from its trigger.
    const onReflow = () => setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", onReflow, true);
    window.addEventListener("resize", onReflow);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", onReflow, true);
      window.removeEventListener("resize", onReflow);
    };
  }, [open]);

  const current = options.find((o) => o.value === value);

  const style: React.CSSProperties | null = rect
    ? (() => {
        const width = Math.max(rect.width, 140);
        // Flip up only when there genuinely isn't room below AND there's more
        // room above — otherwise down is the less surprising direction.
        const openUp =
          rect.bottom + MENU_MAX > window.innerHeight && rect.top > window.innerHeight - rect.bottom;
        const rawLeft = align === "right" ? rect.right - width : rect.left;
        const left = Math.max(8, Math.min(rawLeft, window.innerWidth - width - 8));
        return openUp
          ? { position: "fixed", bottom: window.innerHeight - rect.top + 4, left, minWidth: width }
          : { position: "fixed", top: rect.bottom + 4, left, minWidth: width };
      })()
    : null;

  return (
    <div className={`relative ${className}`}>
      <button
        ref={triggerRef}
        type="button"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "w-full flex items-center justify-between gap-1 h-7 px-2 rounded-md border border-border/60 bg-background text-[11px] text-foreground hover:border-primary/40 transition-colors",
          open && "border-primary/60",
          triggerClassName,
        )}
      >
        <span className="flex min-w-0 items-center gap-1.5">
          {current?.icon && <current.icon className="h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" />}
          {current?.dot && <Dot color={current.dot} />}
          <span className="truncate">{current?.label ?? value}</span>
        </span>
        <ChevronDown
          className={`w-3 h-3 flex-shrink-0 text-muted-foreground/60 transition-transform ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {open &&
        style &&
        createPortal(
          <div
            ref={menuRef}
            role="listbox"
            style={{ ...style, maxHeight: MENU_MAX }}
            className="z-50 w-max max-w-[260px] overflow-y-auto rounded-lg border border-border/60 bg-card shadow-xl p-1"
          >
            {options.map((o) => {
              const selected = o.value === value;
              return (
                <button
                  key={o.value}
                  type="button"
                  role="option"
                  aria-selected={selected}
                  onClick={() => {
                    onChange(o.value);
                    setOpen(false);
                  }}
                  className={`w-full flex items-center justify-between gap-2 px-2 py-1.5 rounded-md text-[11px] transition-colors ${
                    selected
                      ? "bg-primary/10 text-primary font-medium"
                      : "text-foreground/80 hover:bg-muted/50"
                  }`}
                >
                  <span className="flex min-w-0 items-center gap-1.5">
                    {o.icon && (
                      <o.icon
                        className={`h-3.5 w-3.5 flex-shrink-0 ${
                          selected ? "" : "text-muted-foreground"
                        }`}
                      />
                    )}
                    {o.dot && <Dot color={o.dot} />}
                    <span className="truncate">{o.label}</span>
                  </span>
                  {selected && <Check className="w-3.5 h-3.5 flex-shrink-0" />}
                </button>
              );
            })}
          </div>,
          document.body,
        )}
    </div>
  );
}
