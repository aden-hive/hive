import { describe, it, expect } from "vitest";
import { splitSkills } from "./skills";

describe("splitSkills", () => {
  it("split at commas and enumeration marks", () => {
    expect(splitSkills("Brand strategy, visual identity,design systems")).toEqual(["Brand strategy", "visual identity", "design systems"]);
    expect(splitSkills("插画、取材；识图")).toEqual(["插画", "取材", "识图"]);
  });

  it("keep what is in brackets with its skill", () => {
    expect(splitSkills("drawing (ink, watercolour), teasing")).toEqual(["drawing (ink, watercolour)", "teasing"]);
    expect(splitSkills("插画（水彩，油画）、取材（标签 / 搜索）")).toEqual(["插画（水彩，油画）", "取材（标签 / 搜索）"]);
  });

  it("give nothing for blank text", () => {
    expect(splitSkills("  ,  ")).toEqual([]);
  });
});
