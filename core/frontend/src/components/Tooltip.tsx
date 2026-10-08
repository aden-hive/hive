import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";

/** Gap between the cursor and the tooltip box, and the box's max width. */
const CURSOR_OFFSET_X = 14;
const CURSOR_OFFSET_Y = 18;
const MAX_W = 280;
const SHOW_DELAY_MS = 200;

/**
 * Lightweight tooltip. Wrap any trigger element.
 *
 * Replaces the native `title` attribute, whose ~1s OS-controlled delay and
 * unstyled chrome read as slow and cheap. This shows after a snappy 200ms,
 * hides instantly, and renders on an inverted surface so it pops against the
 * light header. Trigger elements should still carry their own `aria-label`.
 *
 * Two positioning modes:
 *  • default — centred on the trigger. Good for roomy targets (header buttons).
 *  • `atCursor` — follows the pointer, rendered in a portal on <body>. Use this
 *    for small targets inside scrollable/clipped containers (e.g. a 2px status
 *    dot in the sidebar): a trigger-centred box there lands nowhere near the
 *    cursor and gets cut off by the container's overflow.
 */
export function Tooltip({
  label,
  children,
  side = "bottom",
  className = "",
  atCursor = false,
}: {
  label: string;
  children: ReactNode;
  side?: "top" | "bottom";
  /** Extra classes for the wrapper — e.g. `flex-shrink-0` when the trigger sits
   *  in a flex row and must not collapse (a status dot). */
  className?: string;
  /** Anchor the tooltip to the pointer instead of the trigger. */
  atCursor?: boolean;
}) {
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null);
  const timer = useRef<number | null>(null);

  // Never leave a pending show-timer behind on unmount (the sidebar remounts
  // its rows constantly) — it would fire against a dead component.
  useEffect(() => {
    return () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    };
  }, []);

  const track = (e: MouseEvent) => {
    const { clientX: x, clientY: y } = e;
    if (cursor) {
      setCursor({ x, y });
      return;
    }
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCursor({ x, y }), SHOW_DELAY_MS);
  };

  const clear = () => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
    setCursor(null);
  };

  const pos = side === "bottom" ? "top-full mt-2" : "bottom-full mb-2";

  if (!atCursor) {
    return (
      <span className={`relative inline-flex group/tip ${className}`}>
        {children}
        <span
          role="tooltip"
          className={`pointer-events-none absolute left-1/2 z-50 -translate-x-1/2 ${pos} whitespace-nowrap rounded-md bg-foreground px-2 py-1 text-[11px] font-medium leading-none text-background shadow-lg ring-1 ring-black/5 opacity-0 scale-95 transition-[opacity,transform] duration-100 ease-out group-hover/tip:opacity-100 group-hover/tip:scale-100 group-hover/tip:delay-200`}
        >
          {label}
        </span>
      </span>
    );
  }

  return (
    <span
      className={`relative inline-flex ${className}`}
      onMouseEnter={track}
      onMouseMove={track}
      onMouseLeave={clear}
    >
      {children}
      {cursor &&
        createPortal(
          <span
            role="tooltip"
            style={{
              // Keep the box on-screen: flip to the cursor's left near the right
              // edge, and above it near the bottom.
              left: Math.min(
                cursor.x + CURSOR_OFFSET_X,
                window.innerWidth - MAX_W - 8,
              ),
              top: Math.min(
                cursor.y + CURSOR_OFFSET_Y,
                window.innerHeight - 48,
              ),
              maxWidth: MAX_W,
            }}
            className="pointer-events-none fixed z-[100] rounded-md bg-foreground px-2 py-1 text-[11px] font-medium leading-snug text-background shadow-lg ring-1 ring-black/5"
          >
            {label}
          </span>,
          document.body,
        )}
    </span>
  );
}
