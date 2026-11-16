import { describe, it, expect } from "vitest";
import { isQueenDecommissioned, type MeSnapshot } from "./me";

function snapshot(queens: NonNullable<MeSnapshot["preferences"]>["queens"]): MeSnapshot {
  return { user: null, preferences: { queens }, subscription: null, balance: null };
}

describe("isQueenDecommissioned", () => {
  it("before any choice, keep only the shipped functions outside the starting team waiting", () => {
    const fresh = snapshot({});

    expect(isQueenDecommissioned(fresh, "queen_growth")).toBe(false);
    expect(isQueenDecommissioned(fresh, "queen_legal")).toBe(true);
    expect(isQueenDecommissioned(fresh, "queen_mira")).toBe(false);
  });

  it("once choices are saved, hide exactly the queens decommissioned", () => {
    const chosen = snapshot({ queen_legal: { decommissioned: false }, queen_mira: { decommissioned: true } });

    expect(isQueenDecommissioned(chosen, "queen_legal")).toBe(false);
    expect(isQueenDecommissioned(chosen, "queen_mira")).toBe(true);
    expect(isQueenDecommissioned(chosen, "queen_lan")).toBe(false);
  });
});
