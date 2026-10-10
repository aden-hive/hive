/**
 * A thinking model writes a thought before every tool call. Rendered as
 * separate rows, one turn's working scattered above and below the queen's
 * reply; mergeThinkingTurns folds a thinking turn's activity into one run.
 */
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/MarkdownContent", () => ({ default: () => null }));
vi.mock("@/components/charts/ChartToolDetail", () => ({ default: () => null }));
vi.mock("@/components/TerminalToolDetail", () => ({ default: () => null }));
vi.mock("@/components/WorkerRunBubble", () => ({ default: () => null }));
vi.mock("@/components/QueenPortraitGlyph", () => ({ default: () => null }));

import { mergeThinkingTurns, type ChatMessage } from "@/components/ChatPanel";

const msg = (id: string, type?: ChatMessage["type"]): ChatMessage => ({
  id,
  agent: "Queen",
  agentColor: "",
  content: type === "reasoning" ? `thought ${id}` : "",
  timestamp: "",
  type,
  role: type === "user" ? undefined : "queen",
});
const user = (id: string) => ({ kind: "message", msg: msg(id, "user") });
const reply = (id: string) => ({ kind: "message", msg: msg(id) });
const run = (key: string, ...messages: ChatMessage[]) => ({ kind: "tool_status_group", key, messages, createdAt: 0 });

const shape = (items: ReturnType<typeof mergeThinkingTurns>) =>
  items.map((it) =>
    it.kind === "tool_status_group"
      ? `run:${(it as ReturnType<typeof run>).messages.map((m) => m.id).join(",")}`
      : `msg:${(it as ReturnType<typeof user>).msg.id}`,
  );

describe("mergeThinkingTurns", () => {
  it("folds a thinking turn's runs into the first, in order", () => {
    const items = [
      user("u1"),
      run("a", msg("r1", "reasoning")),
      reply("q1"),
      run("b", msg("t1", "tool_status"), msg("r2", "reasoning"), msg("t2", "tool_status")),
      user("u2"),
    ];

    expect(shape(mergeThinkingTurns(items))).toEqual(["msg:u1", "run:r1,t1,r2,t2", "msg:q1", "msg:u2"]);
  });

  it("leaves a turn without thinking as it was", () => {
    const items = [user("u1"), run("a", msg("t1", "tool_status")), reply("q1"), run("b", msg("t2", "tool_status"))];

    expect(shape(mergeThinkingTurns(items))).toEqual(["msg:u1", "run:t1", "msg:q1", "run:t2"]);
  });

  it("keeps turns apart", () => {
    const items = [
      user("u1"),
      run("a", msg("r1", "reasoning")),
      user("u2"),
      run("b", msg("r2", "reasoning")),
      reply("q2"),
      run("c", msg("t3", "tool_status")),
    ];

    expect(shape(mergeThinkingTurns(items))).toEqual(["msg:u1", "run:r1", "msg:u2", "run:r2,t3", "msg:q2"]);
  });
});
