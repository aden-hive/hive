import { api } from "./client";

/** One conversation of a Claude Code queen: the queen it is with, and how far it has come. */
export interface ClaudeCodeConversation {
  session_id: string;
  peer: string;
  peer_name: string;
  /** A turn of hers is running in it now. */
  running: boolean;
  letters: number;
  last_at: string | null;
}

/** A queen run by Claude Code (`queen_mail.claude_code` in configuration.json). */
export interface ClaudeCodeQueen {
  id: string;
  name: string;
  title: string;
  permission_mode: string;
  /** How she pays: an Anthropic API key, or a Claude plan signed in on this computer (at the user's own risk). */
  auth: "api_key" | "subscription";
  model: string | null;
  conversations: ClaudeCodeConversation[];
}

/** One thing in a conversation: a letter she was handed, what she said, a tool she called, or what it returned. */
export interface TranscriptEntry {
  at: string;
  kind: "letter" | "text" | "tool" | "result";
  text: string;
  tool?: string;
  error?: boolean;
}

export const claudeCodeQueensApi = {
  list: () => api.get<{ queens: ClaudeCodeQueen[] }>("/claude-code-queens"),

  transcript: (queenId: string, sessionId: string) =>
    api.get<{ entries: TranscriptEntry[] }>(`/claude-code-queens/${queenId}/conversations/${sessionId}`),
};
