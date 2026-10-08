import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import { useSkillIndex } from "@/hooks/use-skill-index";
import { formatUseSkillTags, shortSkillLabel, type SkillCapsule } from "@/data/skill-capsules";

/**
 * A contenteditable message composer that renders inline
 * `<read_skill>name</read_skill>` markers as atomic, deletable chips and
 * `{{placeholder}}` fill-ins as editable highlighted spans — while the caret
 * flows around everything as normal text. Its `value` is the plain text WITH
 * those markers, so it's a drop-in for a <textarea> that understands skills and
 * placeholders.
 *
 * Editing model: after every keystroke the DOM is reflowed from the serialized
 * text (so chips/highlights stay correct anywhere in the text), and the caret
 * is restored by counting "units" (each text char = 1, each chip = 1) — a count
 * that is invariant across the reflow. IME composition is excluded so Asian
 * input isn't interrupted.
 */
export interface SkillTextEditorHandle {
  focus: () => void;
  /** Insert a skill chip at the current caret (or end if unfocused). */
  insertSkill: (name: string) => void;
}

interface SkillTextEditorProps {
  value: string;
  onChange: (value: string) => void;
  /** Enter (without Shift) while the typeahead is closed. */
  onSubmit?: () => void;
  onFocus?: () => void;
  placeholder?: string;
  disabled?: boolean;
  minHeightPx?: number;
  maxHeightPx?: number;
  className?: string;
  /** Where the "/" suggestion list opens relative to the editor. */
  suggestionPlacement?: "up" | "down";
}

const MAX_SUGGESTIONS = 8;

// A "/"-token ending at the caret: slash at start or after whitespace, then
// label chars and no double-space. Capture group 2 is the typed query.
const SLASH_RE = /(^|\s)\/([\p{L}\p{N} -]*?)$/u;

// One ordered segment of the editor content: prose, a skill chip, or a
// {{placeholder}} fill-in. `raw` for placeholders preserves the exact braces
// text so serialization round-trips byte-for-byte.
type Seg =
  | { type: "text"; value: string }
  | { type: "skill"; name: string }
  | { type: "ph"; label: string; value: string };

// Where to drop the caret after a reflow: inside a text node at an offset, or
// immediately before a chip element.
type CaretTarget =
  | { kind: "offset"; node: Node; offset: number }
  | { kind: "before"; before: HTMLElement };

// Matches a skill marker OR a {{placeholder}}, whichever comes first.
const SEGMENT_RE =
  /<(?:use|read)_skill>([\s\S]*?)<\/(?:use|read)_skill>|(\{\{\s*[^}]+?\s*\}\})/g;

function parseSegments(text: string): Seg[] {
  const segs: Seg[] = [];
  const re = new RegExp(SEGMENT_RE.source, "g");
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) segs.push({ type: "text", value: text.slice(last, m.index) });
    if (m[1] !== undefined) {
      const name = m[1].trim();
      if (name) segs.push({ type: "skill", name });
    } else if (m[2] !== undefined) {
      // m[2] is the whole `{{…}}`; split the inner into `label` and optional
      // `::value` (the user-entered fill).
      const inner = m[2].slice(2, -2).trim();
      const sep = inner.indexOf("::");
      const label = (sep >= 0 ? inner.slice(0, sep) : inner).trim();
      const value = sep >= 0 ? inner.slice(sep + 2).trim() : "";
      if (label) segs.push({ type: "ph", label, value });
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) segs.push({ type: "text", value: text.slice(last) });
  return segs;
}

// A signature of the chip/placeholder structure (ignoring plain-text content).
// When this is unchanged between keystrokes, the DOM doesn't need a rebuild —
// only when a marker/placeholder appears, disappears, or changes.
function structureSig(text: string): string {
  return parseSegments(text)
    // Key ph by label only — editing a pill's value must NOT trigger a rebuild.
    .map((s) => (s.type === "skill" ? `s:${s.name}` : s.type === "ph" ? `p:${s.label}` : "t"))
    .join("|");
}

function isChip(node: Node | null | undefined): node is HTMLElement {
  return (
    !!node &&
    node.nodeType === Node.ELEMENT_NODE &&
    !!(node as HTMLElement).dataset.skill
  );
}

function matchesSkill(c: SkillCapsule, q: string): boolean {
  if (q === "") return true;
  const query = q.toLowerCase();
  const label = c.label.toLowerCase();
  const name = c.name.replace(/^hive\./, "").toLowerCase();
  return (
    label.startsWith(query) ||
    label.split(/\s+/).some((w) => w.startsWith(query)) ||
    name.startsWith(query) ||
    label.includes(query)
  );
}


// Serialize any DOM subtree (the editor, or a cloned selection fragment) back
// to plain text with inline markers. Skill chips → `<read_skill>name</read_skill>`,
// placeholder spans serialize via their text (`{{…}}`), <br> → newline. Shared
// by the editor's value serialization AND by copy/cut so a pill survives the
// clipboard intact.
function serializeDom(root: Node): string {
  let out = "";
  const walk = (node: Node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      out += (node as Text).data;
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    const elt = node as HTMLElement;
    if (elt.dataset.skill) {
      out += formatUseSkillTags([elt.dataset.skill]);
      return;
    }
    if (elt.dataset.phLabel !== undefined) {
      const value = (elt.dataset.phValue ?? "").trim();
      out += value
        ? `{{${elt.dataset.phLabel}::${value}}}`
        : `{{${elt.dataset.phLabel}}}`;
      return;
    }
    if (elt.tagName === "BR") {
      out += "\n";
      return;
    }
    const isBlock = elt.tagName === "DIV" || elt.tagName === "P";
    if (isBlock && out && !out.endsWith("\n")) out += "\n";
    elt.childNodes.forEach(walk);
  };
  root.childNodes.forEach(walk);
  return out;
}

// Caret position at a viewport point — Chromium (Electron) exposes
// caretRangeFromPoint; the standards name is a fallback for completeness.
function caretRangeFromPoint(x: number, y: number): Range | null {
  if (document.caretRangeFromPoint) return document.caretRangeFromPoint(x, y);
  const doc = document as unknown as {
    caretPositionFromPoint?: (
      x: number,
      y: number,
    ) => { offsetNode: Node; offset: number } | null;
  };
  const pos = doc.caretPositionFromPoint?.(x, y);
  if (pos) {
    const r = document.createRange();
    r.setStart(pos.offsetNode, pos.offset);
    r.collapse(true);
    return r;
  }
  return null;
}

export const SkillTextEditor = forwardRef<SkillTextEditorHandle, SkillTextEditorProps>(
  function SkillTextEditor(
    {
      value,
      onChange,
      onSubmit,
      onFocus,
      placeholder = "",
      disabled = false,
      minHeightPx = 24,
      maxHeightPx = 160,
      className = "",
      suggestionPlacement = "down",
    },
    ref,
  ) {
    const editorRef = useRef<HTMLDivElement | null>(null);
    const lastValueRef = useRef<string>("");
    const lastSigRef = useRef<string>("");
    const composingRef = useRef(false);
    const { capsules } = useSkillIndex();
    const labelFor = useCallback(
      (name: string) =>
        capsules.find((c) => c.name === name)?.label ?? name.replace(/^hive\./, ""),
      [capsules],
    );

    const [typeahead, setTypeahead] = useState<{
      open: boolean;
      query: string;
      activeIndex: number;
    }>({ open: false, query: "", activeIndex: 0 });

    // Popover for editing a placeholder pill's value. `pill` is the live DOM
    // node; we write its value back and reflow on save.
    const [phEdit, setPhEdit] = useState<{
      pill: HTMLElement;
      label: string;
      value: string;
      top: number;
      left: number;
    } | null>(null);

    const suggestions = useMemo(() => {
      if (!typeahead.open) return [] as SkillCapsule[];
      return capsules.filter((c) => matchesSkill(c, typeahead.query)).slice(0, MAX_SUGGESTIONS);
    }, [typeahead.open, typeahead.query, capsules]);

    // --- DOM construction -------------------------------------------------

    const makeChip = useCallback(
      (name: string): HTMLSpanElement => {
        const span = document.createElement("span");
        span.dataset.skill = name;
        span.contentEditable = "false";
        // draggable so the pill can be picked up and moved; cursor signals it.
        span.draggable = true;
        span.className =
          "inline-flex items-center align-baseline mx-0.5 rounded-full border border-primary/50 bg-primary/5 text-primary px-1.5 py-0.5 text-[10px] font-medium cursor-grab active:cursor-grabbing";
        span.textContent = shortSkillLabel(labelFor(name));
        span.title = labelFor(name);
        return span;
      },
      [labelFor],
    );

    const makePlaceholderSpan = useCallback((label: string, value: string): HTMLSpanElement => {
      const span = document.createElement("span");
      span.dataset.ph = "true";
      span.dataset.phLabel = label;
      span.dataset.phValue = value;
      // Atomic pill (not directly type-into). Clicking it opens a popover to
      // fill/edit the value; an empty pill shows the label as a faded hint.
      span.contentEditable = "false";
      span.className =
        "cursor-pointer rounded px-1 align-baseline ring-1 ring-amber-500/30 bg-amber-400/20 " +
        "text-amber-800 dark:text-amber-200 transition-colors hover:bg-amber-400/30" +
        (value ? "" : " italic opacity-70");
      span.appendChild(document.createTextNode(value || label));
      // Delete affordance — removes the whole pill.
      const x = document.createElement("button");
      x.type = "button";
      x.dataset.phX = "true";
      x.contentEditable = "false";
      x.tabIndex = -1;
      x.textContent = "×";
      x.setAttribute("aria-label", `Remove ${label}`);
      x.className = "ml-1 cursor-pointer align-baseline leading-none opacity-40 hover:opacity-100";
      span.appendChild(x);
      return span;
    }, []);

    const renderToDom = useCallback(
      (text: string) => {
        const el = editorRef.current;
        if (!el) return;
        el.textContent = "";
        for (const seg of parseSegments(text)) {
          if (seg.type === "text") {
            if (seg.value) el.appendChild(document.createTextNode(seg.value));
          } else if (seg.type === "skill") {
            el.appendChild(makeChip(seg.name));
          } else {
            el.appendChild(makePlaceholderSpan(seg.label, seg.value));
          }
        }
        el.dataset.empty = text.length === 0 ? "true" : "false";
      },
      [makeChip, makePlaceholderSpan],
    );

    const serialize = useCallback((): string => {
      const el = editorRef.current;
      return el ? serializeDom(el) : "";
    }, []);

    // --- caret as a "unit" index (text char = 1, chip = 1) ----------------

    const countUnits = useCallback((node: Node): number => {
      let n = 0;
      const walk = (nd: Node) => {
        if (nd.nodeType === Node.TEXT_NODE) n += (nd as Text).data.length;
        else if (nd.nodeType === Node.ELEMENT_NODE) {
          const e = nd as HTMLElement;
          // Skill chips and placeholder pills are atomic — one unit each.
          if (e.dataset.skill || e.dataset.phLabel !== undefined) n += 1;
          else e.childNodes.forEach(walk);
        }
      };
      node.childNodes.forEach(walk);
      return n;
    }, []);

    const caretUnitIndex = useCallback((): number => {
      const el = editorRef.current;
      const sel = window.getSelection();
      if (!el || !sel || sel.rangeCount === 0) return 0;
      const range = sel.getRangeAt(0);
      if (!el.contains(range.endContainer)) return countUnits(el);
      const pre = range.cloneRange();
      pre.selectNodeContents(el);
      pre.setEnd(range.endContainer, range.endOffset);
      return countUnits(pre.cloneContents());
    }, [countUnits]);

    const setCaretToUnit = useCallback((index: number) => {
      const el = editorRef.current;
      const sel = window.getSelection();
      if (!el || !sel) return;
      let remaining = index;
      let target: CaretTarget | null = null;
      const walk = (nd: Node) => {
        if (target) return;
        if (nd.nodeType === Node.TEXT_NODE) {
          const len = (nd as Text).data.length;
          if (remaining <= len) {
            target = { kind: "offset", node: nd, offset: remaining };
            remaining = 0;
            return;
          }
          remaining -= len;
          return;
        }
        if (nd.nodeType === Node.ELEMENT_NODE) {
          const e = nd as HTMLElement;
          if (e.dataset.skill || e.dataset.phLabel !== undefined) {
            if (remaining === 0) {
              target = { kind: "before", before: e };
              return;
            }
            remaining -= 1;
            return;
          }
          e.childNodes.forEach(walk);
        }
      };
      el.childNodes.forEach(walk);
      // Indirect through a typed const so TS doesn't narrow `target` to `null`
      // (it can't see the mutation inside the `walk` closure).
      const t = target as CaretTarget | null;
      const r = document.createRange();
      if (!t) {
        r.selectNodeContents(el);
        r.collapse(false);
      } else if (t.kind === "before") {
        r.setStartBefore(t.before);
        r.collapse(true);
      } else {
        r.setStart(t.node, t.offset);
        r.collapse(true);
      }
      sel.removeAllRanges();
      sel.addRange(r);
    }, []);

    const autosize = useCallback(() => {
      const el = editorRef.current;
      if (!el) return;
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, maxHeightPx)}px`;
    }, [maxHeightPx]);

    // Keep the caret visible after a programmatic caret restore (reflow). Setting
    // a selection via Range doesn't auto-scroll the scroll container the way
    // native typing does, so a Shift+Enter newline at the bottom of a long,
    // scrolled message would otherwise leave the caret below the viewport.
    const scrollCaretIntoView = useCallback(() => {
      const el = editorRef.current;
      const sel = window.getSelection();
      if (!el || !sel || sel.rangeCount === 0) return;
      const range = sel.getRangeAt(0);
      if (!el.contains(range.endContainer)) return;
      const caret = range.cloneRange();
      caret.collapse(false);
      let rect = caret.getBoundingClientRect();
      if (rect.height === 0) {
        // A collapsed caret on a blank line reports no box; measure with a
        // temporary zero-width marker, then remove it (caret stays put).
        const marker = document.createElement("span");
        marker.textContent = "​";
        caret.insertNode(marker);
        rect = marker.getBoundingClientRect();
        marker.remove();
      }
      const host = el.getBoundingClientRect();
      if (rect.bottom > host.bottom) el.scrollTop += rect.bottom - host.bottom + 2;
      else if (rect.top < host.top) el.scrollTop -= host.top - rect.top + 2;
    }, []);

    // --- typeahead --------------------------------------------------------

    const textBeforeCaret = useCallback((): string => {
      const el = editorRef.current;
      const sel = window.getSelection();
      if (!el || !sel || sel.rangeCount === 0) return "";
      const range = sel.getRangeAt(0);
      if (!el.contains(range.endContainer)) return "";
      const pre = range.cloneRange();
      pre.selectNodeContents(el);
      pre.setEnd(range.endContainer, range.endOffset);
      const frag = pre.cloneContents();
      let out = "";
      const walk = (node: Node) => {
        if (node.nodeType === Node.TEXT_NODE) out += (node as Text).data;
        else if (node.nodeType === Node.ELEMENT_NODE) {
          const elt = node as HTMLElement;
          if (elt.dataset.skill) out += " ";
          else elt.childNodes.forEach(walk);
        }
      };
      frag.childNodes.forEach(walk);
      return out;
    }, []);

    const refreshTypeahead = useCallback(() => {
      const before = textBeforeCaret();
      const m = before.match(SLASH_RE);
      if (!m || m[2].includes("  ")) {
        setTypeahead((t) => (t.open ? { ...t, open: false } : t));
        return;
      }
      setTypeahead({ open: true, query: m[2], activeIndex: 0 });
    }, [textBeforeCaret]);

    // --- the core reflow: serialize, rebuild, restore caret ---------------

    const reflow = useCallback(() => {
      const v = serialize();
      const idx = caretUnitIndex();
      renderToDom(v);
      setCaretToUnit(idx);
      lastValueRef.current = v;
      lastSigRef.current = structureSig(v);
      onChange(v);
      autosize();
      refreshTypeahead();
      scrollCaretIntoView();
    }, [serialize, caretUnitIndex, renderToDom, setCaretToUnit, onChange, autosize, refreshTypeahead, scrollCaretIntoView]);

    const handleInput = useCallback(() => {
      if (composingRef.current) {
        // Don't reflow mid-IME composition; just keep the value synced.
        const v = serialize();
        lastValueRef.current = v;
        onChange(v);
        return;
      }
      const v = serialize();
      // Only rebuild the DOM (and disturb the caret) when a chip/placeholder
      // actually appeared, vanished, or changed. Plain typing keeps the
      // browser's own caret and editing intact.
      if (structureSig(v) !== lastSigRef.current) {
        reflow();
        return;
      }
      lastValueRef.current = v;
      onChange(v);
      const el = editorRef.current;
      if (el) el.dataset.empty = v.length === 0 ? "true" : "false";
      autosize();
      refreshTypeahead();
    }, [serialize, onChange, reflow, autosize, refreshTypeahead]);

    // --- skill insertion --------------------------------------------------

    const insertChipAtCaret = useCallback(
      (name: string) => {
        const el = editorRef.current;
        if (!el) return;
        el.focus();
        const sel = window.getSelection();
        let range: Range;
        if (sel && sel.rangeCount > 0 && el.contains(sel.getRangeAt(0).endContainer)) {
          range = sel.getRangeAt(0);
        } else {
          range = document.createRange();
          range.selectNodeContents(el);
          range.collapse(false);
        }
        range.deleteContents();
        const chip = makeChip(name);
        const space = document.createTextNode(" ");
        range.insertNode(space);
        range.insertNode(chip);
        // Caret just after the trailing space.
        const after = document.createRange();
        after.setStartAfter(space);
        after.collapse(true);
        sel?.removeAllRanges();
        sel?.addRange(after);
        reflow();
      },
      [makeChip, reflow],
    );

    const selectSuggestion = useCallback(
      (index: number) => {
        const pick = suggestions[index];
        if (!pick) return;
        // Remove the trailing "/query" before the caret, then drop in the chip.
        const sel = window.getSelection();
        if (sel && sel.rangeCount > 0) {
          const range = sel.getRangeAt(0);
          const node = range.endContainer;
          if (node.nodeType === Node.TEXT_NODE) {
            const textNode = node as Text;
            const end = range.endOffset;
            const start = Math.max(0, end - (typeahead.query.length + 1));
            textNode.deleteData(start, end - start);
            const r = document.createRange();
            r.setStart(textNode, start);
            r.collapse(true);
            sel.removeAllRanges();
            sel.addRange(r);
          }
        }
        insertChipAtCaret(pick.name);
        setTypeahead({ open: false, query: "", activeIndex: 0 });
      },
      [suggestions, typeahead.query, insertChipAtCaret],
    );

    // --- deletion of an adjacent chip ------------------------------------

    const chipAdjacent = useCallback(
      (dir: "back" | "fwd"): HTMLElement | null => {
        const sel = window.getSelection();
        if (!sel || !sel.isCollapsed || sel.rangeCount === 0) return null;
        const range = sel.getRangeAt(0);
        const node = range.endContainer;
        const offset = range.endOffset;
        if (node.nodeType === Node.TEXT_NODE) {
          const len = (node as Text).data.length;
          if (dir === "back" && offset > 0) return null; // a char precedes
          if (dir === "fwd" && offset < len) return null; // a char follows
          const sib = dir === "back" ? node.previousSibling : node.nextSibling;
          return isChip(sib) ? sib : null;
        }
        if (node.nodeType === Node.ELEMENT_NODE) {
          const idx = dir === "back" ? offset - 1 : offset;
          const child = node.childNodes[idx];
          return isChip(child) ? child : null;
        }
        return null;
      },
      [],
    );

    const deleteChip = useCallback(
      (chip: HTMLElement) => {
        const sel = window.getSelection();
        const next = chip.nextSibling;
        const prev = chip.previousSibling;
        chip.remove();
        const r = document.createRange();
        if (next && next.nodeType === Node.TEXT_NODE) r.setStart(next, 0);
        else if (prev && prev.nodeType === Node.TEXT_NODE)
          r.setStart(prev, (prev as Text).data.length);
        else if (editorRef.current) {
          r.selectNodeContents(editorRef.current);
          r.collapse(false);
        }
        r.collapse(true);
        sel?.removeAllRanges();
        sel?.addRange(r);
        reflow();
      },
      [reflow],
    );

    // --- imperative handle ------------------------------------------------

    useImperativeHandle(
      ref,
      () => ({
        focus: () => editorRef.current?.focus(),
        insertSkill: (name: string) => insertChipAtCaret(name),
      }),
      [insertChipAtCaret],
    );

    // --- controlled sync (external value changes) -------------------------

    useEffect(() => {
      if (value === lastValueRef.current) return;
      renderToDom(value);
      lastValueRef.current = value;
      lastSigRef.current = structureSig(value);
      // If the editor is focused, keep the caret at the end of the new content.
      if (editorRef.current && document.activeElement === editorRef.current) {
        setCaretToUnit(countUnits(editorRef.current));
      }
      autosize();
    }, [value, renderToDom, setCaretToUnit, countUnits, autosize]);

    // --- key handling -----------------------------------------------------

    const handleKeyDown = useCallback(
      (e: React.KeyboardEvent<HTMLDivElement>) => {
        if (typeahead.open && suggestions.length > 0) {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setTypeahead((t) => ({ ...t, activeIndex: (t.activeIndex + 1) % suggestions.length }));
            return;
          }
          if (e.key === "ArrowUp") {
            e.preventDefault();
            setTypeahead((t) => ({
              ...t,
              activeIndex: (t.activeIndex - 1 + suggestions.length) % suggestions.length,
            }));
            return;
          }
          if (e.key === "Enter" || e.key === "Tab") {
            e.preventDefault();
            selectSuggestion(typeahead.activeIndex);
            return;
          }
          if (e.key === "Escape") {
            e.preventDefault();
            setTypeahead({ open: false, query: "", activeIndex: 0 });
            return;
          }
        }
        if (e.key === "Backspace") {
          const chip = chipAdjacent("back");
          if (chip) {
            e.preventDefault();
            deleteChip(chip);
            return;
          }
        }
        if (e.key === "Delete") {
          const chip = chipAdjacent("fwd");
          if (chip) {
            e.preventDefault();
            deleteChip(chip);
            return;
          }
        }
        if (e.key === "Enter") {
          e.preventDefault();
          if (e.shiftKey) {
            // Insert a literal newline ourselves so the browser can't drop in a
            // <div>/<br> that serializes to a double line break.
            const sel = window.getSelection();
            if (sel && sel.rangeCount > 0) {
              const range = sel.getRangeAt(0);
              range.deleteContents();
              const nl = document.createTextNode("\n");
              range.insertNode(nl);
              const after = document.createRange();
              after.setStartAfter(nl);
              after.collapse(true);
              sel.removeAllRanges();
              sel.addRange(after);
              reflow();
            }
            return;
          }
          onSubmit?.();
        }
      },
      [typeahead.open, typeahead.activeIndex, suggestions.length, selectSuggestion, chipAdjacent, deleteChip, reflow, onSubmit],
    );

    const handlePaste = useCallback(
      (e: React.ClipboardEvent<HTMLDivElement>) => {
        e.preventDefault();
        const text = e.clipboardData.getData("text/plain");
        if (!text) return;
        const sel = window.getSelection();
        if (!sel || sel.rangeCount === 0) return;
        const range = sel.getRangeAt(0);
        range.deleteContents();
        const node = document.createTextNode(text);
        range.insertNode(node);
        const after = document.createRange();
        after.setStartAfter(node);
        after.collapse(true);
        sel.removeAllRanges();
        sel.addRange(after);
        reflow();
      },
      [reflow],
    );

    // --- copy / cut: put the marker on the clipboard, not the label ------

    const draggingChipRef = useRef<HTMLElement | null>(null);

    const handleCopy = useCallback((e: React.ClipboardEvent<HTMLDivElement>) => {
      const sel = window.getSelection();
      const el = editorRef.current;
      if (!sel || sel.rangeCount === 0 || sel.isCollapsed || !el) return;
      const range = sel.getRangeAt(0);
      if (!el.contains(range.commonAncestorContainer)) return;
      // Serialize the selection so a pill copies as its <read_skill> marker and
      // pastes back as a chip — here or anywhere else.
      e.preventDefault();
      e.clipboardData.setData("text/plain", serializeDom(range.cloneContents()));
    }, []);

    const handleCut = useCallback(
      (e: React.ClipboardEvent<HTMLDivElement>) => {
        const sel = window.getSelection();
        const el = editorRef.current;
        if (!sel || sel.rangeCount === 0 || sel.isCollapsed || !el) return;
        const range = sel.getRangeAt(0);
        if (!el.contains(range.commonAncestorContainer)) return;
        e.preventDefault();
        e.clipboardData.setData("text/plain", serializeDom(range.cloneContents()));
        range.deleteContents();
        sel.removeAllRanges();
        sel.addRange(range);
        reflow();
      },
      [reflow],
    );

    // --- drag a pill to a new position -----------------------------------
    //
    // We drive the move ourselves rather than letting contentEditable's native
    // node-move run, so serialization and the caret stay correct.

    const handleDragStart = useCallback((e: React.DragEvent<HTMLDivElement>) => {
      const chip = (e.target as HTMLElement)?.closest?.("[data-skill]") as HTMLElement | null;
      if (!chip || !editorRef.current?.contains(chip) || !chip.dataset.skill) return;
      draggingChipRef.current = chip;
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", formatUseSkillTags([chip.dataset.skill]));
    }, []);

    const handleDragOver = useCallback((e: React.DragEvent<HTMLDivElement>) => {
      if (!draggingChipRef.current) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
    }, []);

    const handleDrop = useCallback(
      (e: React.DragEvent<HTMLDivElement>) => {
        const chip = draggingChipRef.current;
        draggingChipRef.current = null;
        const el = editorRef.current;
        if (!chip || !el || !chip.dataset.skill) return;
        e.preventDefault();
        const range = caretRangeFromPoint(e.clientX, e.clientY);
        // Bail on a drop onto the chip itself (no-op) or outside the editor.
        if (
          !range ||
          !el.contains(range.startContainer) ||
          chip.contains(range.startContainer)
        )
          return;
        // Don't land the chip *inside* a {{placeholder}} highlight (that would
        // splice the marker into the braces text) — drop after it instead.
        const host =
          range.startContainer.nodeType === Node.ELEMENT_NODE
            ? (range.startContainer as HTMLElement)
            : range.startContainer.parentElement;
        const ph = host?.closest("[data-ph]") as HTMLElement | null;
        if (ph) {
          range.setStartAfter(ph);
        }
        const fresh = makeChip(chip.dataset.skill);
        range.collapse(true);
        range.insertNode(fresh);
        chip.remove();
        const after = document.createRange();
        after.setStartAfter(fresh);
        after.collapse(true);
        const sel = window.getSelection();
        sel?.removeAllRanges();
        sel?.addRange(after);
        reflow();
      },
      [makeChip, reflow],
    );

    const handleDragEnd = useCallback(() => {
      draggingChipRef.current = null;
    }, []);

    // Commit the popover's value to its pill and rebuild.
    const savePhEdit = useCallback(() => {
      if (!phEdit) return;
      phEdit.pill.dataset.phValue = phEdit.value.trim();
      setPhEdit(null);
      reflow();
    }, [phEdit, reflow]);

    // mousedown (not click) so we can preventDefault before the caret/blur
    // shifts: the ✕ deletes the pill; clicking the pill body opens the editor.
    const handleMouseDown = useCallback(
      (e: React.MouseEvent<HTMLDivElement>) => {
        const targetEl = e.target as HTMLElement;
        const x = targetEl.closest?.("[data-ph-x]") as HTMLElement | null;
        if (x) {
          const pill = x.closest("[data-ph-label]") as HTMLElement | null;
          if (pill) {
            e.preventDefault();
            pill.remove();
            reflow();
          }
          return;
        }
        const pill = targetEl.closest?.("[data-ph-label]") as HTMLElement | null;
        if (pill && editorRef.current?.contains(pill)) {
          e.preventDefault();
          const rect = pill.getBoundingClientRect();
          setPhEdit({
            pill,
            label: pill.dataset.phLabel ?? "",
            value: pill.dataset.phValue ?? "",
            top: rect.bottom + 6,
            left: rect.left,
          });
        }
      },
      [reflow],
    );

    return (
      <div className="relative">
        <div
          ref={editorRef}
          role="textbox"
          aria-multiline="true"
          contentEditable={!disabled}
          suppressContentEditableWarning
          data-empty="true"
          data-placeholder={placeholder}
          onInput={handleInput}
          onKeyDown={handleKeyDown}
          onMouseDown={handleMouseDown}
          onPaste={handlePaste}
          onCopy={handleCopy}
          onCut={handleCut}
          onDragStart={handleDragStart}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
          onDragEnd={handleDragEnd}
          onFocus={onFocus}
          onCompositionStart={() => (composingRef.current = true)}
          onCompositionEnd={() => {
            composingRef.current = false;
            reflow();
          }}
          onBlur={() =>
            setTimeout(() => setTypeahead((t) => (t.open ? { ...t, open: false } : t)), 120)
          }
          style={{ minHeight: minHeightPx, maxHeight: maxHeightPx }}
          className={
            "w-full overflow-y-auto whitespace-pre-wrap break-words outline-none " +
            "data-[empty=true]:before:content-[attr(data-placeholder)] " +
            "before:text-muted-foreground/60 before:pointer-events-none " +
            className
          }
        />
        {typeahead.open && suggestions.length > 0 && (
          <div
            className={
              "absolute left-0 right-0 z-40 rounded-lg border border-border/60 bg-popover shadow-lg overflow-hidden " +
              (suggestionPlacement === "up" ? "bottom-full mb-1" : "top-full mt-1")
            }
          >
            <ul className="max-h-56 overflow-y-auto py-1">
              {suggestions.map((c, i) => (
                <li key={c.name}>
                  <button
                    type="button"
                    onMouseDown={(e) => {
                      e.preventDefault();
                      selectSuggestion(i);
                    }}
                    className={
                      "w-full px-3 py-1.5 text-left text-xs transition-colors " +
                      (i === typeahead.activeIndex
                        ? "bg-primary/10 text-primary"
                        : "text-foreground hover:bg-primary/10")
                    }
                  >
                    {c.label}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {phEdit && (
          <>
            {/* click-away commits the value */}
            <div
              className="fixed inset-0 z-40"
              onMouseDown={(e) => {
                e.preventDefault();
                savePhEdit();
              }}
            />
            <div
              className="fixed z-50 w-60 rounded-xl border border-border/60 bg-popover p-3 shadow-xl"
              style={{ top: phEdit.top, left: phEdit.left }}
              onMouseDown={(e) => e.stopPropagation()}
            >
              <label className="mb-1.5 block px-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                {phEdit.label}
              </label>
              <input
                autoFocus
                value={phEdit.value}
                onChange={(e) =>
                  setPhEdit((cur) => (cur ? { ...cur, value: e.target.value } : cur))
                }
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    savePhEdit();
                  } else if (e.key === "Escape") {
                    e.preventDefault();
                    setPhEdit(null);
                  }
                }}
                placeholder={`Enter ${phEdit.label}`}
                className="w-full rounded-lg border border-border/60 bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/40 focus:outline-none focus:ring-1 focus:ring-primary"
              />
              <p className="mt-1.5 px-0.5 text-[10px] text-muted-foreground/70">
                Enter to save · saved for next time
              </p>
            </div>
          </>
        )}
      </div>
    );
  },
);
