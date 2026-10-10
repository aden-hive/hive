import { useEffect, useState } from "react";
import { useFullMotion } from "@/lib/motion";

// ASCII only: the labels are monospace, and a glyph from a fallback font would
// change the width mid-scramble.
const GLYPHS = "01<>/\\|=+*#%";

function scramble(text: string, progress: number): string {
  const settled = Math.floor(text.length * progress);
  let out = text.slice(0, settled);
  for (const ch of text.slice(settled)) {
    out += ch === " " ? " " : GLYPHS[Math.floor(Math.random() * GLYPHS.length)];
  }
  return out;
}

/** A short label that decodes from noise, left to right. The real text is in
 *  the DOM from the first frame for assistive tech; the noise is decorative. */
export function ScrambleText({
  text,
  className = "",
  delayMs = 0,
  durationMs = 560,
}: {
  text: string;
  className?: string;
  delayMs?: number;
  durationMs?: number;
}) {
  const full = useFullMotion();
  const [shown, setShown] = useState(() => (full ? scramble(text, 0) : text));

  useEffect(() => {
    if (!full) {
      setShown(text);
      return;
    }
    const start = performance.now() + delayMs;
    let frame = 0;
    const tick = (now: number) => {
      const progress = Math.min(1, Math.max(0, (now - start) / durationMs));
      setShown(scramble(text, progress));
      if (progress < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [text, full, delayMs, durationMs]);

  if (!full) return <span className={className}>{text}</span>;
  return (
    <span className={className}>
      <span className="sr-only">{text}</span>
      <span aria-hidden>{shown}</span>
    </span>
  );
}
