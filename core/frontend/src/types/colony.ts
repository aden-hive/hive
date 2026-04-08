export interface Colony {
  id: string;
  name: string;
  agentPath: string;
  description: string;
  status: "running" | "idle";
  unreadCount: number;
  queenId: string;
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
  colonyId: string;
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

export interface UserProfile {
  displayName: string;
  about: string;
}
