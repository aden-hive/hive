export interface Colony {
  id: string;
  name: string;
  agentPath: string;
  description: string;
  status: "active" | "idle" | "parked";
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

import type { PortraitDescriptor } from "@/api/queens";

export interface QueenProfileSummary {
  id: string;
  name: string;
  title: string;
  portrait?: PortraitDescriptor | null;
  /** True when an avatar.{jpg|png|webp} exists on disk for this queen.
   * Renderers gate the `<img>` load on this so first-time users don't
   * see a 404 for every queen in the sidebar. */
  has_avatar?: boolean;
  /** True for user-created queens (not part of the shipped catalog).
   * The leader catalog groups these under "Custom". */
  custom?: boolean;
}

export interface UserProfile {
  displayName: string;
  about: string;
}
