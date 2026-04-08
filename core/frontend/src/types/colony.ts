export interface Colony {
  id: string;
  name: string;
  agentPath: string;
  description: string;
  status: "running" | "idle";
  unreadCount: number;
  queenId: string;
  /** Queen profile ID from session data (e.g. "queen_technology") */
  queenProfileId: string | null;
  /** Backend session ID when live */
  sessionId: string | null;
  /** Number of active sessions */
  sessionCount: number;
  /** Number of total runs */
  runCount: number;
}

export interface QueenBee {
  id: string;
  name: string;
  role: string;
  /** Colony this queen is currently managing (if any). */
  colonyId?: string;
  status: "online" | "offline";
}

export interface Template {
  id: string;
  title: string;
  description: string;
  category: string;
  icon: string;
  agentPath: string;
}

export interface QueenProfileSummary {
  id: string;
  name: string;
  title: string;
}

export interface UserProfile {
  displayName: string;
  about: string;
}
