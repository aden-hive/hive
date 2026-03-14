import { describe, expect, it } from "vitest";

import { isRunButtonDisabled } from "./run-button-state";

describe("isRunButtonDisabled", () => {
  it("disables run when there are no nodes", () => {
    expect(isRunButtonDisabled(0, "running")).toBe(true);
  });

  it("disables run during planning", () => {
    expect(isRunButtonDisabled(4, "planning")).toBe(true);
  });

  it("disables run during building", () => {
    expect(isRunButtonDisabled(4, "building")).toBe(true);
  });

  it("allows run in staging when nodes exist", () => {
    expect(isRunButtonDisabled(4, "staging")).toBe(false);
  });

  it("allows run in running view when nodes exist", () => {
    expect(isRunButtonDisabled(4, "running")).toBe(false);
  });
});
