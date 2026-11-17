import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const list = vi.fn();
const read = vi.fn();
const history = vi.fn();
const restore = vi.fn();
const retired = vi.fn();
const remove = vi.fn();

vi.mock("@/api/memories", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/memories")>();
  return {
    ...actual,
    memoriesApi: {
      list: () => list(),
      read: (path: string) => read(path),
      update: vi.fn(),
      delete: (path: string) => remove(path),
      history: (path: string) => history(path),
      restore: (path: string, n: number) => restore(path, n),
      retired: () => retired(),
    },
  };
});
vi.mock("@/context/ColonyContext", () => ({ useColony: () => ({ queenProfiles: [] }) }));
vi.mock("@/lib/me", () => ({ useMe: () => ({ me: null }), isQueenDecommissioned: () => false }));
vi.mock("@/lib/colony-registry", () => ({ orderQueens: (queens: unknown[]) => queens }));

import MemoryLibrary from "./memory-library";

const TEA = {
  path: "global/tea.md",
  filename: "tea.md",
  name: "Tea",
  description: "What Ava drinks",
  scope: "global",
  scope_name: "",
  author: "reflection",
  learned: "2026-03-02",
  confirmed: "2026-04-05",
};
const TEA_TEXT = "---\nname: Tea\n---\nAva drinks pu-erh.\n";

function renderPage() {
  return render(
    <MemoryRouter>
      <MemoryLibrary />
    </MemoryRouter>,
  );
}

describe("MemoryLibrary", () => {
  beforeEach(() => {
    for (const f of [list, read, history, restore, retired, remove]) f.mockReset();
    list.mockResolvedValue({ memories: [TEA] });
    read.mockResolvedValue({ ...TEA, content: TEA_TEXT });
    retired.mockResolvedValue({ retired: [] });
  });

  it("says who wrote a memory and when it was last confirmed", async () => {
    renderPage();

    // The day is in the reader's locale.
    const day = new Date("2026-04-05T00:00:00").toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
    expect(await screen.findByText(`Reflection · confirmed ${day}`)).toBeTruthy();
  });

  it("shows a memory's history and puts an earlier version back", async () => {
    history.mockResolvedValue({
      path: TEA.path,
      changes: [
        { n: 0, at: "2026-03-02T09:00:00+00:00", op: "write", file: "tea.md", author: "reflection", reason: "", sources: [], before: null, after: "Ava drinks oolong.\n" },
        { n: 3, at: "2026-04-05T09:00:00+00:00", op: "write", file: "tea.md", author: "queen", reason: "she switched", sources: [], before: "Ava drinks oolong.\n", after: TEA_TEXT },
      ],
    });
    restore.mockResolvedValue({ ...TEA, content: "Ava drinks oolong.\n" });
    renderPage();

    fireEvent.click(await screen.findByText("Tea"));
    fireEvent.click(await screen.findByRole("button", { name: /History/ }));
    const changes = within(await screen.findByRole("list", { name: "History" })).getAllByRole("listitem");

    // Newest first; the newest is what the file says now.
    expect(changes[0].textContent).toContain("Queen wrote — she switched");
    expect(changes[0].textContent).toContain("current");
    fireEvent.click(within(changes[1]).getByRole("button", { name: /Restore/ }));

    await waitFor(() => expect(restore).toHaveBeenCalledWith("global/tea.md", 0));
  });

  it("lists what was removed and restores it", async () => {
    retired.mockResolvedValue({
      retired: [{ path: "global/pets.md", filename: "pets.md", n: 5, at: "2026-04-01T10:00:00+00:00", author: "reflection", reason: "merged into home.md", scope: "global", scope_name: "" }],
    });
    restore.mockResolvedValue({ ...TEA, path: "global/pets.md", filename: "pets.md", name: "Pets", content: "Ava has a cat.\n" });
    renderPage();

    fireEvent.click(await screen.findByText("Removed (1)"));
    expect(screen.getByText(/Reflection — merged into home.md/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Restore/ }));

    await waitFor(() => expect(restore).toHaveBeenCalledWith("global/pets.md", 5));
    expect(await screen.findByText("Pets")).toBeTruthy();
    expect(screen.queryByText("Removed (1)")).toBeNull();
  });

  it("says a deleted memory can be restored", async () => {
    renderPage();

    fireEvent.click(await screen.findByText("Tea"));
    fireEvent.click(await screen.findByRole("button", { name: /Delete/ }));

    expect(screen.getByText("Delete this memory? It can be restored from Removed.")).toBeTruthy();
  });
});
