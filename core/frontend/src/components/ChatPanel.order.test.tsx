/**
 * ChatPanel must render messages in chronological order even when the
 * `messages` prop arrives unsorted. A forked-session restore racing the
 * live SSE re-subscribe can hand ChatPanel an out-of-order array; the
 * transcript must still read top-to-bottom oldest → newest.
 */
import { createElement } from "react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
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

/** A real-bubble message (user / untyped queen) — these carry
 *  `data-message-id` in the DOM, unlike tool pills or dividers. */
function bubble(i: number, createdAt: number): ChatMessage {
  const isUser = i % 2 === 0;
  return {
    id: `m${i}`,
    agent: isUser ? "You" : "Queen",
    agentColor: "",
    content: `message ${i}`,
    timestamp: "",
    type: isUser ? "user" : undefined,
    role: isUser ? undefined : "queen",
    thread: "queen-dm",
    createdAt,
  };
}

describe("ChatPanel — chronological rendering", () => {
  it("renders an unsorted messages prop in createdAt order", async () => {
    const ChatPanel = (await import("@/components/ChatPanel")).default;

    // 12 messages, createdAt strictly increasing with index, spanning
    // three calendar days so day dividers are exercised too.
    const day = 24 * 60 * 60 * 1000;
    const base = Date.UTC(2026, 4, 14, 12, 0, 0);
    const ordered = Array.from({ length: 12 }, (_, i) =>
      bubble(i, base + Math.floor(i / 4) * day + i * 60_000),
    );
    // Hand ChatPanel a deliberately shuffled array.
    const shuffled = [
      ordered[7], ordered[2], ordered[11], ordered[0], ordered[5],
      ordered[9], ordered[1], ordered[6], ordered[3], ordered[10],
      ordered[4], ordered[8],
    ];

    const { container } = render(
      createElement(ChatPanel, {
        messages: shuffled,
        onSend: () => {},
        activeThread: "queen-dm",
      } as never),
    );

    const renderedIds = [
      ...container.querySelectorAll<HTMLElement>("[data-message-id]"),
    ].map((el) => el.getAttribute("data-message-id"));

    // All 12 bubbles present (12 < the 30-message initial window).
    expect(renderedIds).toHaveLength(12);
    // …and in chronological order, not the shuffled prop order.
    expect(renderedIds).toEqual(ordered.map((m) => m.id));
  });
});
