import { describe, expect, it } from "vitest";
import { agentTypesToClose, connectionsToOpen } from "./multi-sse-diff";

describe("multi-sse-diff", () => {
  it("closes when agent type is removed from sessions", () => {
    const current = new Map([["queen-dm", { sessionId: "s1" }]]);
    expect(agentTypesToClose(current, {})).toEqual(["queen-dm"]);
  });

  it("closes when session ID changes for the same agent type", () => {
    const current = new Map([["researcher-agent", { sessionId: "session_abc123" }]]);
    const sessions = { "researcher-agent": "session_xyz789" };
    expect(agentTypesToClose(current, sessions)).toEqual(["researcher-agent"]);
  });

  it("does not close when agent type and session ID are unchanged", () => {
    const current = new Map([["queen-dm", { sessionId: "s1" }]]);
    expect(agentTypesToClose(current, { "queen-dm": "s1" })).toEqual([]);
  });

  it("opens a new connection when agent type is new", () => {
    expect(connectionsToOpen(new Map(), { "queen-dm": "s1" })).toEqual([
      { agentType: "queen-dm", sessionId: "s1" },
    ]);
  });

  it("opens when session ID changes after stale entry would be closed", () => {
    const current = new Map([["researcher-agent", { sessionId: "session_abc123" }]]);
    const sessions = { "researcher-agent": "session_xyz789" };
    expect(connectionsToOpen(current, sessions)).toEqual([
      { agentType: "researcher-agent", sessionId: "session_xyz789" },
    ]);
  });

  it("does not open when session ID is unchanged", () => {
    const current = new Map([["queen-dm", { sessionId: "s1" }]]);
    expect(connectionsToOpen(current, { "queen-dm": "s1" })).toEqual([]);
  });

  it("skips empty session IDs", () => {
    expect(connectionsToOpen(new Map(), { "queen-dm": "" })).toEqual([]);
  });

  it("reconnect flow: close then open on session restart", () => {
    const before = new Map([["colony-worker", { sessionId: "old" }]]);
    const afterSessions = { "colony-worker": "new" };
    const toClose = agentTypesToClose(before, afterSessions);
    expect(toClose).toEqual(["colony-worker"]);

    const mid = new Map(before);
    for (const agentType of toClose) mid.delete(agentType);
    expect(connectionsToOpen(mid, afterSessions)).toEqual([
      { agentType: "colony-worker", sessionId: "new" },
    ]);
  });
});
