import { useMemo, type CSSProperties } from "react";

/**
 * The honeycomb behind a queen's portrait: a lattice centred on it, some cells lit in her colour,
 * fewer the further out. Which cells light is drawn from her id, so each queen keeps a pattern of
 * her own across visits. Sized in CSS (.qp-aura svg); this only lays the cells out.
 */

const R = 40;
const W = Math.sqrt(3) * R;
/** The drawing, in px around the portrait's centre; matches .qp-aura svg. */
const VIEW = { left: -560, top: -400, width: 1680, height: 800 };
/** Cells closer than this lie under the portrait. */
const UNDER = 100;

function seedOf(text: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/** mulberry32: a small, fast, seeded generator of numbers in [0, 1). */
function generator(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function hexPoints(cx: number, cy: number, r: number): string {
  const half = (Math.sqrt(3) * r) / 2;
  return [
    [cx, cy - r],
    [cx + half, cy - r / 2],
    [cx + half, cy + r / 2],
    [cx, cy + r],
    [cx - half, cy + r / 2],
    [cx - half, cy - r / 2],
  ]
    .map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`)
    .join(" ");
}

type Cell = { points: string; lit: number; beacon: boolean; delay: number };

export default function HoneycombAura({ seed }: { seed: string }) {
  const cells = useMemo(() => {
    const random = generator(seedOf(seed));
    const out: Cell[] = [];
    const rows = Math.ceil(VIEW.height / 2 / (1.5 * R)) + 1;
    for (let row = -rows; row <= rows; row++) {
      const cy = row * 1.5 * R;
      const shift = Math.abs(row % 2) === 1 ? W / 2 : 0;
      for (let col = Math.floor(VIEW.left / W) - 1; col <= Math.ceil((VIEW.left + VIEW.width) / W) + 1; col++) {
        const cx = col * W + shift;
        const distance = Math.hypot(cx, cy);
        const [roll, glow, phase] = [random(), random(), random()];
        if (distance < UNDER) continue;
        const near = Math.exp(-(distance - UNDER) / 260);
        const lit = roll < 0.55 * near ? 0.05 + 0.2 * glow * near : 0;
        out.push({ points: hexPoints(cx, cy, R - 3), lit, beacon: !lit && roll > 0.985 && distance < 520, delay: phase * 7 });
      }
    }
    return out;
  }, [seed]);

  return (
    <svg viewBox={`${VIEW.left} ${VIEW.top} ${VIEW.width} ${VIEW.height}`} aria-hidden>
      {cells.map((cell, i) => (
        <polygon
          key={i}
          className="qp-cell"
          points={cell.points}
          data-lit={cell.lit ? "" : undefined}
          data-beacon={cell.beacon ? "" : undefined}
          style={cell.lit ? ({ "--lit": cell.lit.toFixed(3), "--d": `-${cell.delay.toFixed(2)}s` } as CSSProperties) : undefined}
        />
      ))}
    </svg>
  );
}
