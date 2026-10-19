import { useLayoutEffect, useRef, useState, type ElementType, type ReactNode } from "react";
import { useFullMotion } from "@/lib/motion";

interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

interface Line extends Box {
  /** Word boxes, relative to the line's own box. */
  words: Box[];
}

const STAGGER_MS = 90;
const REVEAL_MS = 620;
/** Matches the horizontal bleed of .fx-decrypt-mask. */
const MASK_PAD_X = 3;

/** Lay the host's words out as lines of redaction strips: one box per
 *  rendered line, each holding one strip per word, all relative to `host`. */
function measureLines(host: HTMLElement): Line[] {
  const origin = host.getBoundingClientRect();
  const lines: Line[] = [];
  const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.textContent ?? "";
    for (const match of text.matchAll(/\S+/g)) {
      const start = match.index ?? 0;
      range.setStart(node, start);
      range.setEnd(node, start + match[0].length);
      // A word only splits across lines when it hyphenates; take each piece.
      for (const r of Array.from(range.getClientRects())) {
        if (r.width < 1 || r.height < 1) continue;
        const word = { left: r.left - origin.left, top: r.top - origin.top, width: r.width, height: r.height };
        let line = lines.find((l) => Math.abs(l.top - word.top) < word.height / 2);
        if (!line) {
          line = { ...word, words: [] };
          lines.push(line);
        }
        const right = Math.max(line.left + line.width, word.left + word.width);
        line.left = Math.min(line.left, word.left);
        line.width = right - line.left;
        line.top = Math.min(line.top, word.top);
        line.height = Math.max(line.height, word.height);
        line.words.push(word);
      }
    }
  }
  for (const line of lines) {
    line.words = line.words.map((w) => ({ ...w, left: w.left - line.left, top: w.top - line.top }));
  }
  return lines;
}

/** RhineLab-style decryption: each wrapped line starts as a row of redaction
 *  strips, one per word, and an amber read head sweeps across it writing the
 *  text in, line after line. Non-destructive: the text is laid out and
 *  readable to assistive tech from the first frame, and the overlay is
 *  aria-hidden and removed once the sweep ends. */
export function Decrypt({
  as: Tag = "span",
  children,
  className = "",
  delayMs = 0,
}: {
  as?: ElementType;
  children: ReactNode;
  className?: string;
  delayMs?: number;
}) {
  const full = useFullMotion();
  const ref = useRef<HTMLElement>(null);
  const [lines, setLines] = useState<Line[] | null>(null);

  // Layout effect: the overlay must be in place before the first paint, or
  // the text flashes uncovered for a frame.
  useLayoutEffect(() => {
    const host = ref.current;
    if (!full || !host) return;
    const measured = measureLines(host);
    if (measured.length === 0) return;
    setLines(measured);
    const done = window.setTimeout(() => setLines(null), delayMs + STAGGER_MS * measured.length + REVEAL_MS + 80);
    // On a cold load the first measurement uses the fallback font; once the
    // webfont lands the words move, so lay the strips out again.
    let active = true;
    if (document.fonts && document.fonts.status !== "loaded") {
      void document.fonts.ready.then(() => {
        if (active) setLines((current) => current && measureLines(host));
      });
    }
    return () => {
      active = false;
      window.clearTimeout(done);
    };
    // Plays once per mount (not per content change): re-measuring would
    // re-cover text the user is already reading.
  }, [full, delayMs]);

  return (
    <Tag ref={ref} className={`relative ${className}`}>
      {children}
      {lines && (
        <span aria-hidden className="fx-decrypt">
          {lines.map((line, i) => (
            <span
              key={i}
              className="fx-decrypt-line"
              style={{
                left: line.left,
                top: line.top,
                width: line.width,
                height: line.height,
                animationDelay: `${delayMs + i * STAGGER_MS}ms`,
              }}
            >
              <span className="fx-decrypt-mask">
                {line.words.map((w, j) => (
                  <span
                    key={j}
                    className="fx-decrypt-word"
                    style={{ left: w.left + MASK_PAD_X, width: w.width }}
                  />
                ))}
              </span>
              <span className="fx-decrypt-head" />
            </span>
          ))}
        </span>
      )}
    </Tag>
  );
}
