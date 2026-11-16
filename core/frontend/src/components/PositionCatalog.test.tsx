import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const listRemoved = vi.fn();
const removeQueen = vi.fn();
const restoreQueen = vi.fn();
const createQueen = vi.fn();
const refresh = vi.fn();

vi.mock("@/api/queens", () => ({
  queensApi: {
    listRemoved: () => listRemoved(),
    removeQueen: (id: string) => removeQueen(id),
    restoreQueen: (id: string) => restoreQueen(id),
    createQueen: (body: unknown) => createQueen(body),
    updateProfile: async () => ({}),
  },
}));
vi.mock("@/context/ColonyContext", () => ({
  useColony: () => ({
    refresh,
    queenProfiles: [
      { id: "queen_growth", name: "Steve Jobs", title: "Head of Growth" },
      { id: "queen_mira", name: "Mira", title: "Cartographer", custom: true },
    ],
    queenAvatarVersion: () => 0,
    queenHasAvatar: () => false,
    bumpQueenAvatar: () => {},
  }),
}));

import PositionCatalog from "./PositionCatalog";

function renderCatalog() {
  return render(
    <MemoryRouter initialEntries={["/org-chart"]}>
      <Routes>
        <Route path="/org-chart" element={<PositionCatalog />} />
        <Route path="/queen/:queenId/profile" element={<p>Her profile</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("PositionCatalog", () => {
  beforeEach(() => {
    localStorage.clear();
    for (const f of [listRemoved, removeQueen, restoreQueen, createQueen, refresh]) f.mockReset();
    listRemoved.mockResolvedValue({ queens: [] });
  });

  it("gives every queen a position: a shipped one offers its leaders, one of the user's shows her", async () => {
    renderCatalog();

    expect(screen.getByText("Growth")).toBeTruthy();
    expect(screen.getByText("Current lead")).toBeTruthy();
    expect(screen.getByText("Cartographer")).toBeTruthy();
    expect(screen.getByText("Mira")).toBeTruthy();
    // Hers is on the team from the start, not decommissioned.
    expect(screen.queryByText("Decommissioned")).toBeNull();
  });

  it("removes a position once asked twice, and offers it back to restore", async () => {
    removeQueen.mockResolvedValue({ queen_id: "queen_mira", removed: true });
    restoreQueen.mockResolvedValue({ queen_id: "queen_mira", removed: false });
    renderCatalog();

    fireEvent.click(screen.getAllByTitle("Take this position out of the catalog")[1]);
    expect(removeQueen).not.toHaveBeenCalled();
    listRemoved.mockResolvedValue({ queens: [{ id: "queen_mira", name: "Mira", title: "Cartographer" }] });
    fireEvent.click(within(screen.getByText(/Remove this position\?/).parentElement!).getByText("Remove"));

    await waitFor(() => expect(removeQueen).toHaveBeenCalledWith("queen_mira"));
    expect(refresh).toHaveBeenCalled();
    fireEvent.click(await screen.findByText("Restore"));
    await waitFor(() => expect(restoreQueen).toHaveBeenCalledWith("queen_mira"));
  });

  it("makes a new position a new queen titled by it, and opens her profile", async () => {
    createQueen.mockResolvedValue({ queen: { id: "queen_ivy", name: "Ivy", title: "Illustrator", custom: true } });
    renderCatalog();

    fireEvent.click(screen.getByText("+ New position"));
    fireEvent.change(screen.getByPlaceholderText("e.g. Illustrator, Head of Archives"), { target: { value: " Illustrator " } });
    fireEvent.change(screen.getByPlaceholderText("Who holds it"), { target: { value: "Ivy" } });
    fireEvent.click(screen.getByText("Create"));

    expect(await screen.findByText("Her profile")).toBeTruthy();
    expect(createQueen).toHaveBeenCalledWith({ name: "Ivy", title: "Illustrator", persona: undefined });
  });
});
