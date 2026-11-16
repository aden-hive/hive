import { describe, it, expect } from "vitest";
import { accentFromPixels } from "./avatar-accent";

type Rgb = [number, number, number];

function pixels(...runs: [Rgb, number][]): Uint8ClampedArray {
  return new Uint8ClampedArray(runs.flatMap(([[r, g, b], count]) => Array.from({ length: count }, () => [r, g, b, 255]).flat()));
}

describe("accentFromPixels", () => {
  it("take the hue most of the colourful pixels share, at a lightness that glows", () => {
    // Mostly sky blue, some red, and white and black, which say nothing.
    const accent = accentFromPixels(pixels([[70, 130, 220], 60], [[220, 40, 40], 10], [[255, 255, 255], 30], [[0, 0, 0], 30]));

    const [hue, saturation, lightness] = (accent ?? "").split(" ").map(parseFloat);
    expect(hue).toBeGreaterThan(210);
    expect(hue).toBeLessThan(222);
    expect(saturation).toBeGreaterThanOrEqual(45);
    expect(lightness).toBe(56);
  });

  it("give no accent for a grey picture", () => {
    expect(accentFromPixels(pixels([[128, 128, 128], 50], [[240, 240, 240], 50]))).toBeNull();
  });

  it("pass over see-through pixels", () => {
    const clear = new Uint8ClampedArray([220, 40, 40, 0, 220, 40, 40, 0]);
    expect(accentFromPixels(clear)).toBeNull();
  });
});
