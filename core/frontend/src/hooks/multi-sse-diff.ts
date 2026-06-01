/** Tracked SSE connection metadata (EventSource lives in the hook ref). */
export interface SSEConnectionMeta {
  sessionId: string;
}

/**
 * Agent types whose EventSource should be closed: removed from `sessions` or
 * bound to a different session ID.
 */
export function agentTypesToClose(
  current: ReadonlyMap<string, SSEConnectionMeta>,
  sessions: Record<string, string>,
): string[] {
  const desired = new Set(Object.keys(sessions));
  const toClose: string[] = [];
  for (const [agentType, entry] of current) {
    if (!desired.has(agentType) || sessions[agentType] !== entry.sessionId) {
      toClose.push(agentType);
    }
  }
  return toClose;
}

/**
 * Agent types that need a new EventSource: missing entry or session ID changed.
 */
export function connectionsToOpen(
  current: ReadonlyMap<string, SSEConnectionMeta>,
  sessions: Record<string, string>,
): Array<{ agentType: string; sessionId: string }> {
  const toOpen: Array<{ agentType: string; sessionId: string }> = [];
  for (const [agentType, sessionId] of Object.entries(sessions)) {
    if (!sessionId) continue;
    const existing = current.get(agentType);
    if (existing?.sessionId === sessionId) continue;
    toOpen.push({ agentType, sessionId });
  }
  return toOpen;
}
