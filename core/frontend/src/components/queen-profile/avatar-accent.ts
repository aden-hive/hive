import { useEffect, useState } from "react";

/**
 * The colour a queen's picture is mostly made of, for her profile's glow: the most common hue among
 * its colourful pixels, as an HSL triple ("h s% l%") to use as `hsl(var(--qp-accent) / a)`.
 */

const BINS = 24;
const SAMPLE = 32;

function toHsl(r: number, g: number, b: number): [number, number, number] {
  const max = Math.max(r, g, b) / 255;
  const min = Math.min(r, g, b) / 255;
  const l = (max + min) / 2;
  const d = max - min;
  if (d === 0) return [0, 0, l];
  const s = d / (1 - Math.abs(2 * l - 1));
  let h: number;
  if (max === r / 255) h = ((g - b) / 255 / d) % 6;
  else if (max === g / 255) h = (b - r) / 255 / d + 2;
  else h = (r - g) / 255 / d + 4;
  return [(h * 60 + 360) % 360, s, l];
}

/** The accent of RGBA pixel data, or null when the picture is (nearly) grey. */
export function accentFromPixels(data: Uint8ClampedArray): string | null {
  const weight = new Float64Array(BINS);
  const sin = new Float64Array(BINS);
  const cos = new Float64Array(BINS);
  const sat = new Float64Array(BINS);
  let pixels = 0;
  for (let i = 0; i < data.length; i += 4) {
    if (data[i + 3] < 128) continue;
    pixels += 1;
    const [h, s, l] = toHsl(data[i], data[i + 1], data[i + 2]);
    // Colourful mid-tones say what a picture is; greys, whites and blacks say nothing.
    const w = s * (1 - Math.abs(2 * l - 1));
    if (w < 0.08) continue;
    const bin = Math.floor(h / (360 / BINS)) % BINS;
    const rad = (h * Math.PI) / 180;
    weight[bin] += w;
    sin[bin] += Math.sin(rad) * w;
    cos[bin] += Math.cos(rad) * w;
    sat[bin] += s * w;
  }
  // A hue near a bin's edge splits between two bins, so judge each with its neighbours.
  let best = -1;
  let bestWeight = 0;
  for (let b = 0; b < BINS; b++) {
    const around = weight[(b + BINS - 1) % BINS] + weight[b] + weight[(b + 1) % BINS];
    if (around > bestWeight) {
      best = b;
      bestWeight = around;
    }
  }
  if (best < 0 || bestWeight < pixels * 0.03) return null;
  let x = 0;
  let y = 0;
  let s = 0;
  for (const b of [(best + BINS - 1) % BINS, best, (best + 1) % BINS]) {
    x += cos[b];
    y += sin[b];
    s += sat[b];
  }
  const hue = Math.round(((Math.atan2(y, x) * 180) / Math.PI + 360) % 360);
  // A lightness and saturation that glow on both themes, whatever the picture's own.
  const saturation = Math.round(Math.min(0.82, Math.max(0.45, s / bestWeight)) * 100);
  return `${hue} ${saturation}% 56%`;
}

/**
 * The accent of the picture at `url` (null for none, or a grey one), and whether it is known yet,
 * so the glow can wait for it instead of flashing amber first.
 */
export function useAvatarAccent(url: string | null): { accent: string | null; ready: boolean } {
  const [state, setState] = useState<{ url: string | null; accent: string | null }>({ url: null, accent: null });
  useEffect(() => {
    if (!url) return;
    let cancelled = false;
    const settle = (accent: string | null) => {
      if (!cancelled) setState({ url, accent });
    };
    const img = new Image();
    img.onload = () => {
      try {
        const canvas = document.createElement("canvas");
        canvas.width = SAMPLE;
        canvas.height = SAMPLE;
        const ctx = canvas.getContext("2d", { willReadFrequently: true });
        ctx?.drawImage(img, 0, 0, SAMPLE, SAMPLE);
        settle(ctx ? accentFromPixels(ctx.getImageData(0, 0, SAMPLE, SAMPLE).data) : null);
      } catch {
        // A picture the page may not read keeps the theme's amber.
        settle(null);
      }
    };
    img.onerror = () => settle(null);
    img.src = url;
    return () => {
      cancelled = true;
    };
  }, [url]);
  if (!url) return { accent: null, ready: true };
  return state.url === url ? { accent: state.accent, ready: true } : { accent: null, ready: false };
}
