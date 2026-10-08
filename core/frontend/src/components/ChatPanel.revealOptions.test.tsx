import { createElement } from "react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { fireEvent, render } from "@testing-library/react";
import { installLayoutShim, uninstallLayoutShim } from "@/test/layout";
import type { ChatMessage } from "@/components/ChatPanel";

// Heavy / context-bound dependencies stubbed so ChatPanel renders in jsdom.
vi.mock("@/components/MarkdownContent", () => ({
  default: (p: { content?: string }) =>
    createElement("div", null, String(p?.content ?? "")),
}));
vi.mock("@/components/charts/ChartToolDetail", () => ({ default: () => null }));
vi.mock("@/components/TerminalToolDetail", () => ({ default: () => null }));
vi.mock("@/components/WorkerRunBubble", () => ({ default: () => null }));
vi.mock("@/components/QueenPortraitGlyph", () => ({ default: () => null }));
vi.mock("@/components/QuestionWidget", () => ({ default: () => null }));
vi.mock("@/components/MultiQuestionWidget", () => ({ default: () => null }));
vi.mock("@/components/ParallelSubagentBubble", () => ({ default: () => null }));
vi.mock("@/context/QueenProfileContext", () => ({
  useQueenProfile: () => ({ openQueenProfile: () => {} }),
}));
vi.mock("@/context/ColonyWorkersContext", () => ({
  useColonyWorkers: () => ({ openColonyWorkers: () => {} }),
}));
vi.mock("@/context/ColonyContext", () => ({
  useColony: () => ({ queenProfiles: [], queenAvatarVersion: () => 0 }),
}));
const emptyResult = () =>
  Object.assign([], { votes: [], items: [], sessions: [], skills: [], scopes: [] });
const apiProxy = () =>
  new Proxy({}, { get: () => () => Promise.resolve(emptyResult()) });
// `api` must be on the mock: ChatPanel pulls in use-skill-index, which calls
// skillsApi.listAll() -> api.get() on mount. Without it the component throws
// during commit and the render assertion below fails for an unrelated reason.
vi.mock("@/api/client", () => ({ apiUrl: (p: string) => p, api: apiProxy() }));
vi.mock("@/api/execution", () => ({ executionApi: apiProxy() }));


beforeAll(() => {
  installLayoutShim();
  (globalThis as Record<string, unknown>).IntersectionObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
  };
});
afterAll(uninstallLayoutShim);

/** A tool_status message carrying a completed `hive-crm reveal`. */
function revealMsg(id: string, createdAt: number, candidates: unknown[] | null): ChatMessage {
  const stdout = JSON.stringify({
    revealed: true,
    first_reveal: true,
    ...(candidates ? { migration: { candidates } } : {}),
  });
  return {
    id,
    agent: "Queen",
    agentColor: "",
    content: JSON.stringify({
      tools: [
        {
          name: "terminal_exec",
          done: true,
          isError: false,
          callKey: `k-${id}`,
          args: { command: "hive-crm reveal --json" },
          result: { stdout, stderr: "", exit_code: 0 },
        },
      ],
      allDone: true,
    }),
    timestamp: "",
    type: "tool_status",
    role: "queen",
    thread: "queen-dm",
    createdAt,
  };
}

const CANDIDATES = [
  { colony_id: "email_outreach", name: "email_outreach", table: "email_queue", row_count: 86425 },
  { colony_id: "linkedin_outreach", name: "linkedin_outreach", table: "gong_reactors", row_count: 227 },
];

async function renderPanel(messages: ChatMessage[], onSend = vi.fn()) {
  const ChatPanel = (await import("@/components/ChatPanel")).default;
  // The Open-CRM card is a react-router <Link>, so the panel needs a router.
  const { MemoryRouter } = await import("react-router-dom");
  const r = render(
    createElement(
      MemoryRouter,
      null,
      createElement(ChatPanel, {
        messages,
        onSend,
        activeThread: "queen-dm",
      } as never),
    ),
  );
  return { ...r, onSend };
}

describe("reveal card — campaign import options", () => {
  it("offers one button per campaign, showing the true row count", async () => {
    const { getByText } = await renderPanel([revealMsg("t1", 1000, CANDIDATES)]);

    // The count IS the warning label: 86,425 next to 227 is what lets a user who
    // knows their own pipeline avoid importing a scraped list.
    getByText(/86,425/);
    getByText(/227/);
    getByText(/Not now/);
  });

  it("sends a plain user message naming the campaign the user picked", async () => {
    const { getByText, onSend } = await renderPanel([revealMsg("t1", 1000, CANDIDATES)]);

    fireEvent.click(getByText(/227/).closest("button")!);

    expect(onSend).toHaveBeenCalledTimes(1);
    const [text, thread] = onSend.mock.calls[0];
    // Wording is OURS, not the agent's — a click endorses a label, and the text
    // it turns into must read like something the user would actually type.
    expect(text).toBe("Import the 227 contacts from linkedin_outreach into my CRM.");
    expect(thread).toBe("queen-dm");
  });

  it("declining is a real answer, not silence", async () => {
    const { getByText, onSend } = await renderPanel([revealMsg("t1", 1000, CANDIDATES)]);
    fireEvent.click(getByText(/Not now/));
    expect(onSend).toHaveBeenCalledWith("Don't import anything for now.", "queen-dm");
  });

  it("stops looking askable once answered", async () => {
    const { getByText, queryByText } = await renderPanel([revealMsg("t1", 1000, CANDIDATES)]);
    fireEvent.click(getByText(/Not now/));
    expect(queryByText(/86,425/)).toBeNull();
    expect(queryByText(/Not now/)).toBeNull();
  });

  it("only the newest reveal offers buttons", async () => {
    // An older card still in the transcript must not re-ask a question that was
    // already answered further down. (A user turn separates the two reveals —
    // consecutive tool bursts merge into a single block.)
    const between: ChatMessage = {
      id: "u1", agent: "You", agentColor: "", content: "looks good",
      timestamp: "", type: "user", thread: "queen-dm", createdAt: 1500,
    };
    const { queryAllByText, getByText } = await renderPanel([
      revealMsg("old", 1000, CANDIDATES),
      between,
      revealMsg("new", 2000, [CANDIDATES[1]]),
    ]);
    // Two Open-CRM cards, but only one option set — the newest.
    expect(queryAllByText(/Open CRM/).length).toBe(2);
    expect(queryAllByText(/Not now/).length).toBe(1);
    getByText(/227/);
    expect(queryAllByText(/86,425/).length).toBe(0);
  });

  it("a reveal with no campaigns is just the Open CRM card", async () => {
    const { getByText, queryByText } = await renderPanel([revealMsg("t1", 1000, null)]);
    getByText(/Open CRM/);
    expect(queryByText(/Not now/)).toBeNull();
  });

  it("a refused reveal renders no card at all", async () => {
    // A colony agent's reveal is refused by the CLI (exit 3) — revealing is the
    // setup handoff and belongs to the user's DM. The refusal comes back as a
    // SUCCESSFUL terminal_exec (`isError: false`) carrying a failed command, so
    // nothing above the envelope can tell the two apart. Without this the user
    // gets an "Open CRM" card for a board that was never handed to them.
    const msg = revealMsg("t1", 1000, CANDIDATES);
    const parsed = JSON.parse(msg.content);
    parsed.tools[0].result = {
      stdout: JSON.stringify({
        error: {
          code: "reveal_not_permitted",
          message: "colony agents cannot reveal the CRM",
        },
      }),
      stderr: "",
      exit_code: 3,
    };
    const { queryByText } = await renderPanel([{ ...msg, content: JSON.stringify(parsed) }]);
    expect(queryByText(/Open CRM/)).toBeNull();
    expect(queryByText(/Not now/)).toBeNull();
  });

  it("an error envelope alone is enough to suppress the card", async () => {
    // Belt and braces: if a future path reports the refusal in the payload
    // without propagating the exit code, the card must still stay away.
    const msg = revealMsg("t1", 1000, null);
    const parsed = JSON.parse(msg.content);
    parsed.tools[0].result.stdout = JSON.stringify({
      error: { code: "reveal_not_permitted", message: "nope" },
    });
    const { queryByText } = await renderPanel([{ ...msg, content: JSON.stringify(parsed) }]);
    expect(queryByText(/Open CRM/)).toBeNull();
  });

  it("unparseable reveal output still renders the card", async () => {
    const msg = revealMsg("t1", 1000, CANDIDATES);
    const parsed = JSON.parse(msg.content);
    parsed.tools[0].result.stdout = "migration but not json{{{";
    const { getByText, queryByText } = await renderPanel([{ ...msg, content: JSON.stringify(parsed) }]);
    getByText(/Open CRM/);
    expect(queryByText(/Not now/)).toBeNull();
  });
});
