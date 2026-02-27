/**
 * Shared tab persistence utilities for workspace sessions.
 * Used by both TopBar and workspace.tsx.
 */

import type { ChatMessage } from "@/components/ChatPanel";
import type { GraphNode } from "@/components/AgentGraph";

export const TAB_STORAGE_KEY = "hive:workspace-tabs";

export interface PersistedTabState {
  tabs: Array<{ id: string; agentType: string; label: string; backendSessionId?: string }>;
  activeSessionByAgent: Record<string, string>;
  activeWorker: string;
  sessions?: Record<string, { messages: ChatMessage[]; graphNodes: GraphNode[] }>;
}

export function loadPersistedTabs(): PersistedTabState | null {
  try {
    const raw = localStorage.getItem(TAB_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed.tabs) || parsed.tabs.length === 0) return null;
    return parsed as PersistedTabState;
  } catch {
    return null;
  }
}

const MAX_PERSISTED_MESSAGES = 50;

export function savePersistedTabs(state: PersistedTabState): void {
  try {
    const capped = { ...state };
    if (capped.sessions) {
      const trimmed: typeof capped.sessions = {};
      for (const [id, data] of Object.entries(capped.sessions)) {
        trimmed[id] = {
          messages: data.messages.slice(-MAX_PERSISTED_MESSAGES),
          graphNodes: data.graphNodes,
        };
      }
      capped.sessions = trimmed;
    }
    localStorage.setItem(TAB_STORAGE_KEY, JSON.stringify(capped));
  } catch {
    // localStorage full or unavailable — silently ignore
  }
}
