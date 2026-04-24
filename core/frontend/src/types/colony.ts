export interface Colony {
  id: string;
  name: string;
  agentPath: string;
  description: string;
  status: "running" | "idle";
  unreadCount: number;
  queenId: string;
  queenProfileId: string | null;
  sessionId: string | null;
  sessionCount: number;
  runCount: number;
  queenName: string;
  createdAt: string | null;
  lastActive: string | null;
  task: string;
  icon: string | null;
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
