import {
  useCallback,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";
import { X } from "lucide-react";
import { useSkillIndex } from "@/hooks/use-skill-index";
import {
  buildSteeredMessage,
  capsuleColor,
  shortSkillLabel,
  splitSkillMarkers,
  type SkillCapsule,
} from "@/data/skill-capsules";

const MAX_SUGGESTIONS = 8;

// Match a slash-token ending at the caret: "/", optionally preceded by
// whitespace/start, followed by skill-label characters and no spaces. The
// captured group is the query the user has typed after "/".
const SLASH_RE = /(^|\s)\/([\p{L}\p{N} -]*?)$/u;

function detectQuery(value: string, caret: number): string | null {
  const before = value.slice(0, caret);
  const m = before.match(SLASH_RE);
  if (!m) return null;
  // Disallow a query that already contains a double-space (a sign the user
  // moved past the slash and is just typing normal prose with a "/").
  const q = m[2];
  if (q.includes("  ")) return null;
  return q;
}

function matches(capsule: SkillCapsule, query: string): boolean {
  if (query === "") return true;
  const q = query.toLowerCase();
  const label = capsule.label.toLowerCase();
  const name = capsule.name.replace(/^hive\./, "").toLowerCase();
  // Prefix on the label, on any label word, or on the addressing key.
  if (label.startsWith(q) || name.startsWith(q)) return true;
  return label.split(/\s+/).some((w) => w.startsWith(q));
}

export interface SkillComposer {
  attached: SkillCapsule[];
  suggestions: SkillCapsule[];
  query: string | null;
  isOpen: boolean;
  activeIndex: number;
  /** Re-read the textarea value + caret to update the slash query. Call from onChange. */
  syncQuery: () => void;
  /** Handle composer-relevant keys. Returns true if the key was consumed
   *  (caller should then skip its own Enter-to-send / default handling). */
  handleKeyDown: (e: React.KeyboardEvent) => boolean;
  pick: (capsule: SkillCapsule) => void;
  /** Merge capsules into the pinned set (dedup by name). */
  attach: (capsules: SkillCapsule[]) => void;
  /** Replace the pinned set wholesale (dedup by name) — e.g. when a different
   *  prompt is selected and its skills should supersede the previous ones. */
  replace: (capsules: SkillCapsule[]) => void;
  remove: (name: string) => void;
  reset: () => void;
  /** Split a typed message into LLM-visible + display text given the pins. */
  buildOutgoing: (userText: string) => { message: string; displayMessage: string };
  setActiveIndex: (i: number) => void;
}

/**
 * Drives the `/`-triggered skill typeahead for a textarea composer. The host
 * owns the textarea value/state; this hook layers slash-detection, the
 * suggestion list, and the pinned-capsule set on top.
 */
export function useSkillComposer(opts: {
  value: string;
  onValueChange: (v: string) => void;
  textareaRef: RefObject<HTMLTextAreaElement>;
}): SkillComposer {
  const { value, onValueChange, textareaRef } = opts;
  const { capsules } = useSkillIndex();
  const [attached, setAttached] = useState<SkillCapsule[]>([]);
  const [query, setQuery] = useState<string | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);

  const suggestions = useMemo(() => {
    if (query === null) return [];
    const attachedNames = new Set(attached.map((c) => c.name));
    return capsules
      .filter((c) => !attachedNames.has(c.name) && matches(c, query))
      .slice(0, MAX_SUGGESTIONS);
  }, [query, capsules, attached]);

  const isOpen = query !== null && suggestions.length > 0;

  const syncQuery = useCallback(() => {
    const ta = textareaRef.current;
    const v = ta ? ta.value : value;
    const caret = ta ? ta.selectionStart : v.length;
    const next = detectQuery(v, caret);
    setQuery(next);
    setActiveIndex(0);
  }, [textareaRef, value]);

  const resizeTextarea = useCallback(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
  }, [textareaRef]);

  const pick = useCallback(
    (capsule: SkillCapsule) => {
      const ta = textareaRef.current;
      const v = ta ? ta.value : value;
      const caret = ta ? ta.selectionStart : v.length;
      const before = v.slice(0, caret);
      const after = v.slice(caret);
      const m = before.match(SLASH_RE);
      let newValue = v;
      let newCaret = caret;
      if (m) {
        // Strip the "/query" token (keep the leading whitespace it matched).
        const slashStart = before.length - m[0].length + m[1].length;
        newValue = v.slice(0, slashStart) + after;
        newCaret = slashStart;
      }
      onValueChange(newValue);
      setAttached((prev) =>
        prev.some((c) => c.name === capsule.name) ? prev : [...prev, capsule],
      );
      setQuery(null);
      setActiveIndex(0);
      requestAnimationFrame(() => {
        const t = textareaRef.current;
        if (!t) return;
        t.focus();
        t.selectionStart = t.selectionEnd = newCaret;
        resizeTextarea();
      });
    },
    [textareaRef, value, onValueChange, resizeTextarea],
  );

  const attach = useCallback((caps: SkillCapsule[]) => {
    setAttached((prev) => {
      const have = new Set(prev.map((c) => c.name));
      const next = [...prev];
      for (const c of caps) {
        if (!have.has(c.name)) {
          have.add(c.name);
          next.push(c);
        }
      }
      return next;
    });
  }, []);

  const replace = useCallback((caps: SkillCapsule[]) => {
    const seen = new Set<string>();
    const next: SkillCapsule[] = [];
    for (const c of caps) {
      if (!seen.has(c.name)) {
        seen.add(c.name);
        next.push(c);
      }
    }
    setAttached(next);
  }, []);

  const remove = useCallback((name: string) => {
    setAttached((prev) => prev.filter((c) => c.name !== name));
  }, []);

  const reset = useCallback(() => {
    setAttached([]);
    setQuery(null);
    setActiveIndex(0);
  }, []);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent): boolean => {
      if (query === null || suggestions.length === 0) {
        // Backspace at the very start with no text removes the last capsule —
        // mirrors how chip inputs behave elsewhere in the app.
        if (e.key === "Backspace" && value === "" && attached.length > 0) {
          setAttached((prev) => prev.slice(0, -1));
          return true;
        }
        return false;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setActiveIndex((i) => (i + 1) % suggestions.length);
        return true;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setActiveIndex((i) => (i - 1 + suggestions.length) % suggestions.length);
        return true;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        pick(suggestions[Math.min(activeIndex, suggestions.length - 1)]);
        return true;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setQuery(null);
        return true;
      }
      return false;
    },
    [query, suggestions, activeIndex, pick, value, attached.length],
  );

  const buildOutgoing = useCallback(
    (userText: string) => buildSteeredMessage(userText, attached),
    [attached],
  );

  return {
    attached,
    suggestions,
    query,
    isOpen,
    activeIndex,
    syncQuery,
    handleKeyDown,
    pick,
    attach,
    replace,
    remove,
    reset,
    buildOutgoing,
    setActiveIndex,
  };
}

/** Small colored chip — shared by pinned capsules and card indicators. */
export function SkillCapsuleChip({
  capsule,
  onRemove,
  size = "sm",
}: {
  capsule: SkillCapsule;
  onRemove?: () => void;
  size?: "sm" | "xs";
}) {
  const pad = size === "xs" ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-0.5 text-[11px]";
  const shortLabel = shortSkillLabel(capsule.label);
  return (
    <span
      // Hollow chip in the theme color: orange border + orange text.
      className={`inline-flex items-center gap-1 rounded-full border border-primary/50 bg-transparent text-primary font-medium ${pad}`}
      title={capsule.label}
    >
      {shortLabel}
      {onRemove && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          className="ml-0.5 opacity-60 hover:opacity-100"
          aria-label={`Remove ${capsule.label}`}
        >
          <X className="h-2.5 w-2.5" />
        </button>
      )}
    </span>
  );
}

/**
 * Read-only renderer for text that carries inline `<read_skill>name</read_skill>`
 * markers (the same markers the contenteditable composer emits). Each marker is
 * drawn as an inline chip in place; the surrounding prose is preserved verbatim.
 * Used in chat bubbles and previews. `tone="onPrimary"` keeps chips legible on
 * the orange user-message bubble. When the text has no markers it renders as a
 * plain wrapped string, so it's a safe drop-in anywhere a message is shown.
 */
export function SkillMarkerText({
  text,
  tone = "default",
  className = "",
}: {
  text: string;
  tone?: "default" | "onPrimary";
  className?: string;
}) {
  const { capsules } = useSkillIndex();
  const segments = useMemo(() => splitSkillMarkers(text), [text]);
  if (!segments.some((s) => s.type === "skill")) {
    return (
      <span className={`whitespace-pre-wrap break-words ${className}`}>{text}</span>
    );
  }
  const chipClass =
    tone === "onPrimary"
      ? "border-black/25 text-black/80 bg-black/[0.06]"
      : "border-primary/50 text-primary bg-transparent";
  return (
    <span className={`whitespace-pre-wrap break-words ${className}`}>
      {segments.map((seg, i) => {
        if (seg.type === "text") return <span key={i}>{seg.value}</span>;
        const cap = capsules.find((c) => c.name === seg.name);
        const label = cap ? cap.label : seg.name.replace(/^hive\./, "");
        const short = shortSkillLabel(label);
        return (
          <span
            key={i}
            className={`inline-flex items-center align-baseline mx-0.5 rounded-full border px-1.5 py-0.5 text-[10px] font-medium ${chipClass}`}
            title={label}
          >
            {short}
          </span>
        );
      })}
    </span>
  );
}

/**
 * Single-line row of skill chips. Renders as many as fit on one row and shows a
 * trailing "…" when the rest overflow. Used on cards where vertical space is
 * tight. Trimming is measured imperatively (and re-measured on resize) so it
 * adapts to the actual label widths and card width.
 */
export function SkillCapsuleRow({
  capsules,
  size = "xs",
  className = "mb-3",
}: {
  capsules: SkillCapsule[];
  size?: "sm" | "xs";
  className?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const layout = () => {
      const chips = Array.from(
        container.querySelectorAll<HTMLElement>("[data-chip]"),
      );
      const ellipsis = container.querySelector<HTMLElement>("[data-ellipsis]");
      if (!ellipsis) return;
      // Start from "all visible" so the measurement reflects true widths.
      chips.forEach((c) => (c.style.display = ""));
      ellipsis.style.display = "none";
      const max = container.clientWidth;
      if (container.scrollWidth <= max) return; // everything fits — no "…".
      ellipsis.style.display = "";
      const gap = 4; // matches gap-1 (0.25rem)
      const ellipsisW = ellipsis.offsetWidth;
      let used = 0;
      let overflowing = false;
      chips.forEach((chip, i) => {
        if (overflowing) {
          chip.style.display = "none";
          return;
        }
        const next = used + (i > 0 ? gap : 0) + chip.offsetWidth;
        // Keep room for the trailing "…".
        if (next + gap + ellipsisW > max) {
          chip.style.display = "none";
          overflowing = true;
        } else {
          used = next;
        }
      });
    };
    layout();
    const ro = new ResizeObserver(layout);
    ro.observe(container);
    return () => ro.disconnect();
  }, [capsules]);

  if (capsules.length === 0) return null;
  return (
    <div
      ref={containerRef}
      // Full list on hover — the row trims to one line, so this is how the
      // skills hidden behind the "…" stay discoverable.
      title={capsules.map((c) => c.label).join(", ")}
      className={`flex flex-nowrap items-center gap-1 overflow-hidden ${className}`}
    >
      {capsules.map((c) => (
        <span data-chip key={c.name} className="flex-shrink-0">
          <SkillCapsuleChip capsule={c} size={size} />
        </span>
      ))}
      <span
        data-ellipsis
        className="flex-shrink-0 text-[11px] font-medium text-primary/70"
        style={{ display: "none" }}
        aria-hidden="true"
      >
        …
      </span>
    </div>
  );
}

/** Row of pinned capsules shown above the textarea. */
export function AttachedSkillChips({
  composer,
}: {
  composer: SkillComposer;
}) {
  if (composer.attached.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5 mb-2 px-1">
      {composer.attached.map((c) => (
        <SkillCapsuleChip
          key={c.name}
          capsule={c}
          onRemove={() => composer.remove(c.name)}
        />
      ))}
    </div>
  );
}

/** Floating "/"-typeahead dropdown. Render inside a `relative` container. */
export function SkillSuggestionList({
  composer,
  placement = "up",
}: {
  composer: SkillComposer;
  /** Open above the input ("up", default) or collapse downward ("down"). */
  placement?: "up" | "down";
}) {
  if (!composer.isOpen) return null;
  const pos = placement === "down" ? "top-full mt-2" : "bottom-full mb-2";
  return (
    <div className={`absolute ${pos} left-0 z-30 w-72 max-w-[90vw] rounded-xl border border-border bg-popover shadow-lg overflow-hidden`}>
      <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70 border-b border-border/60">
        Attach a skill
      </div>
      <ul className="max-h-64 overflow-y-auto py-1">
        {composer.suggestions.map((c, i) => {
          const color = capsuleColor(c.domain);
          const active = i === composer.activeIndex;
          return (
            <li key={c.name}>
              <button
                type="button"
                onMouseEnter={() => composer.setActiveIndex(i)}
                onClick={(e) => {
                  e.preventDefault();
                  composer.pick(c);
                }}
                className={`flex w-full items-start gap-2 px-3 py-1.5 text-left transition-colors ${
                  active ? "bg-primary/10" : "hover:bg-muted/60"
                }`}
              >
                <span className={`mt-1 h-2 w-2 flex-shrink-0 rounded-full ${color.dot}`} />
                <span className="min-w-0">
                  <span className="block text-[13px] font-medium text-foreground">{c.label}</span>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
