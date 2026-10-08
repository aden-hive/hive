import { describe, it, expect } from "vitest";
import { queenFunctionLabel, queenLabelFromId } from "./queen-leaders";

/**
 * A queen's display name has exactly ONE definition: the `title` on her profile,
 * which the runtime serves for every catalog queen and the user can edit in the
 * profile panel. These pin that there is no second one to forget — the org chart
 * used to carry its own id → label table, so renaming a queen left it showing
 * the old name indefinitely.
 */
describe("queen display label", () => {
  it("comes from the profile title", () => {
    const profiles = [{ id: "queen_sales", title: "Head of RevOps" }];
    expect(queenFunctionLabel(profiles, "queen_sales")).toBe("RevOps");
  });

  it("follows a rename with no second edit anywhere", () => {
    // The whole point: the same id, a different title, and the label moves.
    const before = [{ id: "queen_sales", title: "Head of Sales" }];
    const after = [{ id: "queen_sales", title: "Head of RevOps" }];
    expect(queenFunctionLabel(before, "queen_sales")).toBe("Sales");
    expect(queenFunctionLabel(after, "queen_sales")).toBe("RevOps");
  });

  it("uses a title that isn't 'Head of …' as-is", () => {
    const profiles = [{ id: "queen_sales", title: "VP Revenue" }];
    expect(queenFunctionLabel(profiles, "queen_sales")).toBe("VP Revenue");
  });

  it("falls back to the id only while profiles are still loading", () => {
    expect(queenFunctionLabel([], "queen_lead_gen")).toBe("Lead Gen");
    expect(queenFunctionLabel([{ id: "queen_sales", title: "" }], "queen_sales")).toBe("Sales");
  });

  it("derives the fallback rather than looking it up", () => {
    // Any future queen id gets a sane placeholder without anyone adding a row.
    expect(queenLabelFromId("queen_brand_design")).toBe("Brand Design");
    expect(queenLabelFromId("queen_some_new_function")).toBe("Some New Function");
  });
});
