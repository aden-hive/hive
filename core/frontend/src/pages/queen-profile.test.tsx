import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const getPersona = vi.fn();
const setPersona = vi.fn();
const refresh = vi.fn();
const openCreateColony = vi.fn();
const setDecommissioned = vi.fn();

vi.mock("@/api/queens", () => ({
  queensApi: {
    getPersona: (id: string) => getPersona(id),
    setPersona: (id: string, fields: unknown) => setPersona(id, fields),
    getOverview: async () => ({
      queen_id: "queen_x",
      memory: { count: 3, limit: 200, by_type: { preference: 2, feedback: 1 } },
      sessions: { count: 7, first: "2026-07-10", last_active: null },
    }),
    getSoul: async () => ({
      queen_id: "queen_x",
      enabled: true,
      mode: "review",
      hour: 4,
      version: 2,
      updated_at: "2026-10-21T04:00:00+08:00",
      sections: [{ key: "now", title: "Now", limit: 40, used: 17, max_age_days: 14, evidence: 1, items: [{ text: "drawing a lantern", date: "2026-10-20" }] }],
      proposal: null,
      history: [],
      reflecting: false,
      probes: 0,
      probing: false,
      last_run: null,
      last_result: null,
    }),
    getLlm: async () => ({ queen_id: "queen_x", section: null, default_model: "model-x" }),
  },
}));
vi.mock("@/api/config", () => ({ configApi: { getProviderLibrary: async () => ({ library: {} }) } }));
vi.mock("@/context/ColonyContext", () => ({
  useColony: () => ({
    queenProfiles: [{ id: "queen_x", name: "Fox", title: "The painter" }],
    colonies: [{ id: "lanterns", name: "Lanterns", queenProfileId: "queen_x", status: "idle", lastActive: null, task: "Paint the lanterns" }],
    refresh,
    queenAvatarVersion: () => 0,
    queenHasAvatar: () => false,
    bumpQueenAvatar: () => {},
  }),
}));
vi.mock("@/context/CreateColonyContext", () => ({ useCreateColony: () => ({ openCreateColony }) }));
vi.mock("@/lib/me", () => ({ useQueenDecommission: () => ({ isDecommissioned: false, setDecommissioned, saving: false }) }));

import QueenProfilePage from "./queen-profile";

const TRAITS = ["[Voice]", "Short lines, **no** speeches.", "", "<hard_invariants>", "She never shouts.", "</hard_invariants>", ""].join("\n");
const PERSONA = { name: "Fox", title: "The painter", core_traits: TRAITS, skills: "drawing (ink, watercolour), teasing" };

/** The page, opened after the given pages (none: opened directly). */
function renderPage(before: string[] = []) {
  const entries = [...before, "/queen/queen_x/profile"];
  return render(
    <MemoryRouter initialEntries={entries} initialIndex={entries.length - 1}>
      <Routes>
        <Route path="/queen/:queenId/profile" element={<QueenProfilePage />} />
        <Route path="/queen/:queenId" element={<p>Her chat</p>} />
        <Route path="/colony/:colonyId" element={<p>The colony</p>} />
        <Route path="/org-chart" element={<p>The org chart</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("QueenProfilePage", () => {
  beforeEach(() => {
    for (const f of [getPersona, setPersona, refresh, openCreateColony, setDecommissioned]) f.mockReset();
    getPersona.mockResolvedValue({ queen_id: "queen_x", persona: PERSONA });
    setPersona.mockImplementation(async (_id: string, fields: Record<string, unknown>) => ({ queen_id: "queen_x", persona: { ...PERSONA, ...fields } }));
  });

  it("shows who she is: her name, a line from her soul, her chapters, skills and numbers", async () => {
    renderPage();

    expect(screen.getByRole("heading", { level: 1, name: "Fox" })).toBeTruthy();
    expect(await screen.findByRole("heading", { name: "Hard invariants" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Voice" })).toBeTruthy();
    // Bold in the text reads as bold; the rest stays as written.
    expect(screen.getByText("no").tagName).toBe("STRONG");
    expect(await screen.findByText("“drawing a lantern”")).toBeTruthy();
    expect(screen.getByText("drawing (ink, watercolour)")).toBeTruthy();
    expect(screen.getByText("teasing")).toBeTruthy();
    // In the reader's own date format.
    expect(screen.getByText(new Date(2026, 6, 10).toLocaleDateString(undefined, { year: "numeric", month: "numeric", day: "numeric" }))).toBeTruthy();
    expect(await screen.findByText("model-x", { selector: "dd" })).toBeTruthy();
  });

  it("saves an edited chapter back into its place in the text", async () => {
    renderPage();

    fireEvent.click(await screen.findByLabelText("Edit “Hard invariants”"));
    fireEvent.change(screen.getByLabelText("“Hard invariants”, as written"), { target: { value: "She never shouts.\nShe never begs." } });
    fireEvent.click(screen.getByText("Save"));

    await waitFor(() => expect(setPersona).toHaveBeenCalled());
    expect(setPersona).toHaveBeenCalledWith("queen_x", { core_traits: TRAITS.replace("She never shouts.\n", "She never shouts.\nShe never begs.\n") });
    expect(await screen.findByText("She never shouts. She never begs.")).toBeTruthy();
  });

  it("adds a pillar she lacked, leaving its empty fields out", async () => {
    renderPage();

    fireEvent.click(await screen.findByText("Hidden background"));
    fireEvent.change(screen.getByLabelText("Hidden background: Past wound"), { target: { value: "  lost a sketchbook " } });
    fireEvent.click(screen.getByText("Save"));

    await waitFor(() => expect(setPersona).toHaveBeenCalledWith("queen_x", { hidden_background: { past_wound: "lost a sketchbook" } }));
  });

  it("renames her in place and tells the rest of the app", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "Hard invariants" });

    fireEvent.click(screen.getByLabelText("Edit her name and title"));
    fireEvent.change(screen.getByLabelText("Her name"), { target: { value: "Vixen" } });
    fireEvent.click(screen.getByText("Save"));

    await waitFor(() => expect(setPersona).toHaveBeenCalledWith("queen_x", { name: "Vixen", title: "The painter" }));
    expect(refresh).toHaveBeenCalled();
    expect(await screen.findByRole("heading", { level: 1, name: "Vixen" })).toBeTruthy();
  });

  it("leads to the colonies she runs", async () => {
    renderPage();

    fireEvent.click(await screen.findByText("Lanterns"));
    expect(await screen.findByText("The colony")).toBeTruthy();
  });

  it("goes back to where she was opened from", async () => {
    renderPage(["/queen/queen_x"]);

    fireEvent.click(screen.getByText("Back"));
    expect(await screen.findByText("Her chat")).toBeTruthy();
  });

  it("goes back to the org chart when opened directly", async () => {
    renderPage();

    fireEvent.click(screen.getByText("Back"));
    expect(await screen.findByText("The org chart")).toBeTruthy();
  });

  it("opens a new colony for her, and her chat", async () => {
    renderPage();

    fireEvent.click(screen.getAllByText("New colony")[0]);
    expect(openCreateColony).toHaveBeenCalledWith({ queenId: "queen_x" });
    fireEvent.click(screen.getByText("Message"));
    expect(await screen.findByText("Her chat")).toBeTruthy();
  });
});
