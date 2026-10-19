import { describe, it, expect } from "vitest";
import { orderQueens, DEFAULT_ACTIVE_QUEEN_IDS } from "./colony-registry";

const ids = (qs: { id: string }[]) => qs.map((q) => q.id);
const mk = (...xs: string[]) => xs.map((id) => ({ id }));

describe("orderQueens", () => {
  it("puts configured (preferred) queens first, in the configured order", () => {
    const profiles = mk(
      "queen_outbound",
      "queen_growth",
      "queen_content_creation",
    );
    const preferred = [
      "queen_growth",
      "queen_content_creation",
      "queen_outbound",
    ];
    expect(ids(orderQueens(profiles, preferred))).toEqual(preferred);
  });

  it("falls back to the default-active GTM order when nothing is configured", () => {
    const profiles = mk(
      "queen_operations",
      "queen_growth",
      "queen_market_research",
    );
    const out = ids(orderQueens(profiles, []));
    expect(out[0]).toBe(DEFAULT_ACTIVE_QUEEN_IDS[0]); // queen_growth
    expect(out.indexOf("queen_growth")).toBeLessThan(
      out.indexOf("queen_market_research"),
    );
    expect(out.indexOf("queen_market_research")).toBeLessThan(
      out.indexOf("queen_operations"),
    );
  });

  it("ranks configured queens above default-active ones", () => {
    const profiles = mk("queen_growth", "queen_legal");
    // legal is configured; growth is only default-active → legal wins.
    expect(ids(orderQueens(profiles, ["queen_legal"]))).toEqual([
      "queen_legal",
      "queen_growth",
    ]);
  });

  it("puts catalog (non-active) queens after active ones", () => {
    const profiles = mk("queen_legal", "queen_growth", "queen_sales");
    const out = ids(orderQueens(profiles, []));
    expect(out[0]).toBe("queen_growth");
    expect(out.indexOf("queen_growth")).toBeLessThan(out.indexOf("queen_sales"));
    expect(out.indexOf("queen_growth")).toBeLessThan(out.indexOf("queen_legal"));
  });

  it("keeps unknown ids last and in input order (stable)", () => {
    const profiles = mk("queen_zzz", "queen_growth", "queen_aaa");
    const out = ids(orderQueens(profiles, []));
    expect(out[0]).toBe("queen_growth");
    expect(out.slice(1)).toEqual(["queen_zzz", "queen_aaa"]);
  });

  it("does not mutate the input array", () => {
    const profiles = mk("queen_outbound", "queen_growth");
    const before = ids(profiles);
    orderQueens(profiles, ["queen_growth"]);
    expect(ids(profiles)).toEqual(before);
  });
});
