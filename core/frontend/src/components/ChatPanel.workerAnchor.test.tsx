/**
 * The link this whole change hangs on:
 *
 *   ChatPanel must open a `worker_run` span from a worker's ANCHOR message
 *   alone — an empty-content, role:"worker" message synthesised from
 *   `execution_started`.
 *
 * Before the worker-event split a bubble only appeared once the worker's first
 * `llm_text_delta` arrived. The server no longer streams that chatter unless
 * the user is watching that worker, so if grouping still needed a text message
 * to seed the span, EVERY unwatched worker would render no bubble at all —
 * which is exactly the "no worker bubbles until I refresh" symptom.
 *
 * WorkerRunBubble is mocked to a probe so this test asserts the GROUPING, not
 * the bubble's internals (those are covered in WorkerRunBubble.meta.test.tsx).
 */
import { createElement } from "react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";
import { installLayoutShim, uninstallLayoutShim } from "@/test/layout";
import type { ChatMessage } from "@/components/ChatPanel";

vi.mock("@/components/MarkdownContent", () => ({
  default: (p: { content?: string }) =>
    createElement("div", null, String(p?.content ?? "")),
}));
vi.mock("@/components/charts/ChartToolDetail", () => ({ default: () => null }));
vi.mock("@/components/TerminalToolDetail", () => ({ default: () => null }));
// Probe: renders the streamId of whatever group ChatPanel handed it.
vi.mock("@/components/WorkerRunBubble", () => ({
  default: (p: { group: { messages: ChatMessage[] }; label?: string }) =>
    createElement(
      "div",
      { "data-worker-run": p.group.messages[0]?.streamId ?? "?" },
      p.label ?? "",
    ),
}));
vi.mock("@/components/QueenPortraitGlyph", () => ({ default: () => null }));
vi.mock("@/components/QuestionWidget", () => ({ default: () => null }));
vi.mock("@/components/MultiQuestionWidget", () => ({ default: () => null }));
vi.mock("@/components/ParallelSubagentBubble", () => ({ default: () => null }));
vi.mock("@/context/QueenProfileContext", () => ({
  useQueenProfile: () => ({ openQueenProfile: () => {} }),
}));
vi.mock("@/context/ColonyWorkersContext", () => ({
  useColonyWorkers: () => ({ openColonyWorkers: () => {}, workers: [] }),
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
// during commit and nothing renders.
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

const base = Date.UTC(2026, 6, 13, 12, 0, 0);

/** Exactly what replayEvent emits for a worker we are NOT watching. */
function anchor(workerId: string, at: number): ChatMessage {
  return {
    id: `worker-anchor-worker:${workerId}`,
    agent: "Worker",
    agentColor: "",
    content: "", // no chatter — this is the whole point
    timestamp: "",
    role: "worker",
    thread: "queen-dm",
    createdAt: at,
    streamId: `worker:${workerId}`,
    executionId: `ex-${workerId}`,
  };
}

function queenText(id: string, at: number): ChatMessage {
  return {
    id,
    agent: "Queen",
    agentColor: "",
    content: "dispatching workers",
    timestamp: "",
    role: "queen",
    thread: "queen-dm",
    createdAt: at,
  };
}

async function renderPanel(messages: ChatMessage[]) {
  const ChatPanel = (await import("@/components/ChatPanel")).default;
  return render(
    createElement(ChatPanel, {
      messages,
      onSend: () => {},
      activeThread: "queen-dm",
    } as never),
  );
}

describe("ChatPanel — worker bubbles from meta anchors alone", () => {
  it("renders a worker_run bubble from an anchor with NO chatter", async () => {
    const { container } = await renderPanel([
      queenText("q1", base),
      anchor("w1", base + 1000),
    ]);

    const runs = [...container.querySelectorAll("[data-worker-run]")];
    expect(runs.map((el) => el.getAttribute("data-worker-run"))).toEqual([
      "worker:w1",
    ]);
  });

  it("renders one bubble per worker for a parallel fan-out", async () => {
    const { container } = await renderPanel([
      queenText("q1", base),
      anchor("w1", base + 1000),
      anchor("w2", base + 2000),
      anchor("w3", base + 3000),
    ]);

    const runs = [...container.querySelectorAll("[data-worker-run]")].map((el) =>
      el.getAttribute("data-worker-run"),
    );
    expect(runs.sort()).toEqual(["worker:w1", "worker:w2", "worker:w3"]);
  });
});
