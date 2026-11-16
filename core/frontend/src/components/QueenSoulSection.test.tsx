import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

const getSoul = vi.fn();
const setSoul = vi.fn();
const decide = vi.fn();
const rollback = vi.fn();
const reflect = vi.fn();
const probe = vi.fn();
vi.mock("@/api/queens", () => ({
  queensApi: {
    getSoul: (id: string) => getSoul(id),
    setSoul: (id: string, s: unknown) => setSoul(id, s),
    decideSoulProposal: (id: string, p: string, a: unknown) => decide(id, p, a),
    rollbackSoul: (id: string, v: number) => rollback(id, v),
    reflectSoul: (id: string, b: boolean) => reflect(id, b),
    probeSoulProposal: (id: string, p: string) => probe(id, p),
  },
}));

import QueenSoulSection from "./QueenSoulSection";

const base = {
  queen_id: "queen_x",
  enabled: true as const,
  mode: "review" as const,
  hour: 4,
  version: 2,
  updated_at: "2026-10-21T04:00:00+08:00",
  sections: [
    { key: "now", title: "Now", limit: 40, used: 17, max_age_days: 14, evidence: 1, items: [{ text: "drawing a lantern", date: "2026-10-20" }] },
    { key: "people", title: "Me and them", limit: 60, used: 0, max_age_days: null, evidence: 2, items: [] },
  ],
  proposal: null,
  history: [
    { version: 2, at: "2026-10-21T04:00:00+08:00", author: "owner", note: "edited by hand", changes: 0 },
    { version: 1, at: "2026-10-20T04:00:00+08:00", author: "her", note: "first draft: 3 of 3 changes", changes: 3 },
  ],
  reflecting: false,
  probes: 0,
  probing: false,
  last_run: "2026-10-21",
  last_result: "2 changes",
};

const proposal = {
  id: "2026-10-22-040000",
  created_at: "2026-10-22T04:00:00+08:00",
  base_version: 2,
  summary: "She promised Ann a cat.",
  status: "pending" as const,
  sources: ["Night owls"],
  bootstrap: false,
  probes: [] as { q: string; anchor: string; before: string; after: string }[],
  edits: [
    { op: "add" as const, section: "now", text: "a cat for Ann next", old: "", date: "2026-10-21", evidence: [{ quote: "the next one will be a cat", where: "Night owls · Fox" }], reason: "", expired: false },
    { op: "remove" as const, section: "now", text: "", old: "drawing a lantern", date: "", evidence: [], reason: "done", expired: false },
  ],
};

describe("QueenSoulSection", () => {
  beforeEach(() => {
    for (const f of [getSoul, setSoul, decide, rollback, reflect, probe]) f.mockReset();
  });

  it("says how to turn it on when she has no soul", async () => {
    getSoul.mockResolvedValue({ queen_id: "queen_x", enabled: false });
    render(<QueenSoulSection queenId="queen_x" />);

    expect(await screen.findByText(/She has no soul yet/)).toBeTruthy();
  });

  it("shows her soul by section with each section's room", async () => {
    getSoul.mockResolvedValue(base);
    render(<QueenSoulSection queenId="queen_x" />);

    expect(await screen.findByText("Version 2")).toBeTruthy();
    expect(screen.getByText(/drawing a lantern/)).toBeTruthy();
    expect(screen.getByText("17 / 40")).toBeTruthy();
    expect(screen.getByText("Items last 14 days")).toBeTruthy();
    expect(screen.getByText("Changes need 2 sources")).toBeTruthy();
    expect(screen.getByText(/last 2026-10-21: 2 changes/)).toBeTruthy();
  });

  it("applies only the changes left ticked", async () => {
    getSoul.mockResolvedValue({ ...base, proposal });
    decide.mockResolvedValue({ ...base, version: 3 });
    render(<QueenSoulSection queenId="queen_x" />);

    expect(await screen.findByText("“the next one will be a cat” — Night owls · Fox")).toBeTruthy();
    expect((screen.getByText("Reflect now") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByLabelText("Apply change 2"));
    fireEvent.click(screen.getByText("Apply selected"));

    await waitFor(() => expect(screen.getByText("Version 3")).toBeTruthy());
    expect(decide).toHaveBeenCalledWith("queen_x", "2026-10-22-040000", [0]);
  });

  it("edits a section by hand, one item per line with an optional date", async () => {
    getSoul.mockResolvedValue(base);
    setSoul.mockResolvedValue({ ...base, version: 3 });
    render(<QueenSoulSection queenId="queen_x" />);

    fireEvent.click(await screen.findByText("Edit"));
    fireEvent.change(screen.getByLabelText("Me and them, one item per line"), { target: { value: "2026-10-21 Ann teases me\nBo is shy" } });
    fireEvent.click(screen.getByText("Save"));

    await waitFor(() => expect(setSoul).toHaveBeenCalled());
    expect(setSoul.mock.calls[0][1]).toEqual({
      now: [{ date: "2026-10-20", text: "drawing a lantern" }],
      people: [
        { date: "2026-10-21", text: "Ann teases me" },
        { date: "", text: "Bo is shy" },
      ],
    });
  });

  it("starts the first draft when nothing is written yet, and restores an old version", async () => {
    getSoul.mockResolvedValue({ ...base, version: 0, history: [] });
    reflect.mockResolvedValue({ started: true });
    const { unmount } = render(<QueenSoulSection queenId="queen_x" />);

    fireEvent.click(await screen.findByText("Write the first draft"));
    await waitFor(() => expect(reflect).toHaveBeenCalledWith("queen_x", true));
    unmount();

    getSoul.mockResolvedValue(base);
    rollback.mockResolvedValue({ ...base, version: 3 });
    render(<QueenSoulSection queenId="queen_x" />);
    fireEvent.click(await screen.findByText("History"));
    fireEvent.click(screen.getByText("Restore"));
    await waitFor(() => expect(rollback).toHaveBeenCalledWith("queen_x", 1));
  });

  it("tries her with the changes and shows the answers side by side", async () => {
    const answered = { ...proposal, probes: [{ q: "what are you drawing?", anchor: "a lantern", before: "still the lantern", after: "a cat, for Ann" }] };
    getSoul.mockResolvedValueOnce({ ...base, probes: 1, proposal }).mockResolvedValue({ ...base, probes: 1, proposal: answered });
    probe.mockResolvedValue({ started: true });
    render(<QueenSoulSection queenId="queen_x" />);

    fireEvent.click(await screen.findByText("Try her with these changes (1 question)"));

    await waitFor(() => expect(screen.getByText("a cat, for Ann")).toBeTruthy());
    expect(probe).toHaveBeenCalledWith("queen_x", "2026-10-22-040000");
    expect(screen.getByText("Like her: a lantern")).toBeTruthy();
    // Before and after, each under its label.
    expect(screen.getByText("still the lantern").querySelector(".qp-probe-label")?.textContent).toBe("Now");
    expect(screen.getByText("a cat, for Ann").querySelector(".qp-probe-label")?.textContent).toBe("With the changes");
  });
});
