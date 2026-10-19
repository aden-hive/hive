import { describe, expect, it } from "vitest";
import { attachmentLabel } from "./attachments";

describe("attachmentLabel", () => {
  it.each([
    ["1787046226164_0 (2).png", "Image 1"],
    ["1787046226164_2.png", "Image 3"],
    ["a3f9c2e1-7b4d-4c1a-9e8f-2b6d1c0e5a7f.png", "Image"],
    ["IMG_20261010_014833.jpg", "Photo"],
    ["image.png", "Pasted image"],
    ["Q3_board-deck_FINAL_v7 (1).pdf", "Q3 board-deck FINAL v7"],
    ["export_1787046480958.csv", "Export"],
    ["Calculus%20Volume%201.pdf", "Calculus Volume 1"],
    ["data/attachments/Screenshot 2026-10-10 at 01.48.33.png", "Screenshot 2026-10-10 at 01.48.33"],
  ])("%s → %s", (fileName, label) => {
    expect(attachmentLabel(fileName).label).toBe(label);
  });

  it("keeps the original basename and the extension", () => {
    expect(attachmentLabel("data/attachments/1787046226164_0 (2).png")).toEqual({
      label: "Image 1",
      ext: "png",
      original: "1787046226164_0 (2).png",
    });
  });
});
