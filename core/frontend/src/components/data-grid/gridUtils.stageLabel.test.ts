/**
 * Stage/option display names.
 *
 * A team that configures its own pipeline names its stages ("In conversation").
 * Showing the raw stored value instead ("in_conversation", "opportunity_contact")
 * is what makes a configured CRM still read as a generic template, so the label
 * from the schema has to win everywhere a stage is rendered.
 */

import { describe, expect, it } from "vitest";
import { optionLabel } from "./gridUtils";

describe("optionLabel", () => {
  it("prefers the schema's label — the name the team actually chose", () => {
    expect(optionLabel({ value: "in_conversation", label: "In conversation" }, "in_conversation"))
      .toBe("In conversation");
  });

  it("humanizes the raw value when no label is defined", () => {
    // Inferred options (colony-local tables) carry no label; a user should still
    // never see a bare snake_case token in a badge.
    expect(optionLabel({ value: "qualified_lead" }, "qualified_lead")).toBe("Qualified lead");
  });

  it("falls back to the cell value when the option is unknown", () => {
    // A record can hold a stage that predates the current pipeline; it must
    // still render legibly rather than blank.
    expect(optionLabel(undefined, "opportunity_contact")).toBe("Opportunity contact");
  });

  it("renders an empty label for an absent value rather than 'undefined'", () => {
    expect(optionLabel(undefined, null)).toBe("");
    expect(optionLabel(undefined, "")).toBe("");
  });

  it("keeps a label that is deliberately not title-case", () => {
    // The team's wording is theirs — don't re-case it.
    expect(optionLabel({ value: "poc", label: "PoC running" }, "poc")).toBe("PoC running");
  });
});
