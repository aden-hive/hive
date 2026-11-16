import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const list = vi.fn();
const transcript = vi.fn();

vi.mock("@/api/claudeCodeQueens", () => ({
  claudeCodeQueensApi: {
    list: () => list(),
    transcript: (queenId: string, sessionId: string) => transcript(queenId, sessionId),
  },
}));

import ClaudeCodeQueenPage from "./claude-code-queen";

const CLAUDE = {
  id: "queen_claude",
  name: "Claude",
  title: "Claude Code",
  permission_mode: "acceptEdits",
  auth: "api_key" as const,
  model: null,
  conversations: [
    { session_id: "s-ava", peer: "queen_ava", peer_name: "Ava", running: true, letters: 2, last_at: "2026-10-25T10:00:04Z" },
    { session_id: "s-ivy", peer: "queen_ivy", peer_name: "Ivy", running: false, letters: 1, last_at: "2026-10-24T09:00:00Z" },
  ],
};

function renderPage(queenId = "queen_claude") {
  return render(
    <MemoryRouter initialEntries={[`/claude-code/${queenId}`]}>
      <Routes>
        <Route path="/claude-code/:queenId" element={<ClaudeCodeQueenPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ClaudeCodeQueenPage", () => {
  beforeEach(() => {
    list.mockReset();
    transcript.mockReset();
    list.mockResolvedValue({ queens: [CLAUDE] });
    transcript.mockImplementation(async (_queen: string, session: string) => ({
      entries:
        session === "s-ava"
          ? [
              { at: "2026-10-25T10:00:00Z", kind: "letter", text: "[Ava(queen_ava)]: Where is the north shore?" },
              { at: "2026-10-25T10:00:01Z", kind: "tool", tool: "Bash", text: '{"command": "ls maps"}' },
              { at: "2026-10-25T10:00:02Z", kind: "result", text: "north.txt", error: false },
              { at: "2026-10-25T10:00:04Z", kind: "text", text: "It is at 61°N." },
            ]
          : [{ at: "2026-10-24T09:00:00Z", kind: "letter", text: "[Ivy(queen_ivy)]: Have you mapped the east?" }],
    }));
  });

  it("opens on her newest conversation and shows what was handed to her, done and said", async () => {
    renderPage();

    expect(await screen.findByText("[Ava(queen_ava)]: Where is the north shore?")).toBeTruthy();
    expect(screen.getByText("Bash")).toBeTruthy();
    expect(screen.getByText("north.txt")).toBeTruthy();
    expect(screen.getByText("It is at 61°N.")).toBeTruthy();
    expect(screen.getByTitle("She is working on it now")).toBeTruthy();
    expect(screen.getByText(/API key · acceptEdits · read only/)).toBeTruthy();
    expect(screen.queryByRole("note")).toBeNull();
    expect(transcript).toHaveBeenCalledWith("queen_claude", "s-ava");
  });

  it("switches to another conversation", async () => {
    renderPage();
    await screen.findByText("It is at 61°N.");

    fireEvent.click(screen.getByText("Ivy"));

    expect(await screen.findByText("[Ivy(queen_ivy)]: Have you mapped the east?")).toBeTruthy();
    await waitFor(() => expect(screen.queryByText("It is at 61°N.")).toBeNull());
  });

  it("says, on a subscription, that it is at the user's own risk", async () => {
    list.mockResolvedValue({ queens: [{ ...CLAUDE, auth: "subscription" }] });
    renderPage();

    expect((await screen.findByRole("note")).textContent).toMatch(/at your own risk/);
    expect(screen.getByText(/subscription · acceptEdits · read only/)).toBeTruthy();
  });

  it("says so when no such queen runs on Claude Code", async () => {
    renderPage("queen_nobody");

    expect(await screen.findByText(/No queen queen_nobody runs on Claude Code here/)).toBeTruthy();
  });
});
