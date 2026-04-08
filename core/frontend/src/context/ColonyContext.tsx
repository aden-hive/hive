import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useRef,
  type ReactNode,
} from "react";
import type { Colony, QueenBee, UserProfile } from "@/types/colony";
import type { DiscoverEntry, LiveSession } from "@/api/types";
import { agentsApi } from "@/api/agents";
import { sessionsApi } from "@/api/sessions";
import { queensApi } from "@/api/queens";
import {
  agentSlug,
  slugToColonyId,
  slugToDisplayName,
} from "@/lib/colony-registry";

// ── localStorage keys ────────────────────────────────────────────────────────

const SIDEBAR_KEY = "hive:sidebar-collapsed";
const UNREAD_KEY = "hive:unread-counts";
const PROFILE_KEY = "hive:user-profile";
const LAST_VISIT_KEY = "hive:colony-last-visit";

function loadBool(key: string, fallback: boolean): boolean {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : v === "true";
  } catch {
    return fallback;
  }
}

function loadJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

// ── Context type ─────────────────────────────────────────────────────────────

interface ColonyContextValue {
  colonies: Colony[];
  queens: QueenBee[];
  loading: boolean;
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (v: boolean) => void;
  userProfile: UserProfile;
  setUserProfile: (p: UserProfile) => void;
  /** Mark a colony as visited (clears unread count) */
  markVisited: (colonyId: string) => void;
  /** Delete a colony (stops sessions, removes all files) */
  deleteColony: (colonyId: string) => Promise<void>;
  /** Refresh colony data from the server */
  refresh: () => void;
}

const ColonyContext = createContext<ColonyContextValue | null>(null);

export function useColony(): ColonyContextValue {
  const ctx = useContext(ColonyContext);
  if (!ctx) throw new Error("useColony must be used within ColonyProvider");
  return ctx;
}

// ── Provider ─────────────────────────────────────────────────────────────────

export function ColonyProvider({ children }: { children: ReactNode }) {
  const [colonies, setColonies] = useState<Colony[]>([]);
  const [queens, setQueens] = useState<QueenBee[]>([]);
  const [loading, setLoading] = useState(true);
  const [sidebarCollapsed, _setSidebarCollapsed] = useState(() =>
    loadBool(SIDEBAR_KEY, false),
  );
  const [userProfile, _setUserProfile] = useState<UserProfile>(() =>
    loadJson(PROFILE_KEY, { displayName: "", about: "" }),
  );
  const [, setLastVisit] = useState<Record<string, number>>(() =>
    loadJson(LAST_VISIT_KEY, {}),
  );

  const coloniesRef = useRef<Colony[]>(colonies);
  useEffect(() => {
    coloniesRef.current = colonies;
  }, [colonies]);

  const setSidebarCollapsed = useCallback((v: boolean) => {
    _setSidebarCollapsed(v);
    localStorage.setItem(SIDEBAR_KEY, String(v));
  }, []);

  const setUserProfile = useCallback((p: UserProfile) => {
    _setUserProfile(p);
    localStorage.setItem(PROFILE_KEY, JSON.stringify(p));
  }, []);

  const markVisited = useCallback((colonyId: string) => {
    setLastVisit((prev) => {
      const next = { ...prev, [colonyId]: Date.now() };
      localStorage.setItem(LAST_VISIT_KEY, JSON.stringify(next));
      return next;
    });
    // Clear unread for this colony
    setColonies((prev) =>
      prev.map((c) =>
        c.id === colonyId ? { ...c, unreadCount: 0 } : c,
      ),
    );
  }, []);

  // Full fetch: /discover + /sessions — rebuilds colonies and queens from scratch.
  // Only called on mount, visibility change, and after create/delete.
  const fetchColonies = useCallback(async () => {
    try {
      const [discoverResult, sessionsResult, queenProfilesResult] = await Promise.all([
        agentsApi.discover(),
        sessionsApi.list().catch(() => ({ sessions: [] as LiveSession[] })),
        queensApi.list().catch(() => ({ queens: [] as { id: string; name: string; title: string }[] })),
      ]);

      // Skip "Framework" agents — those are internal to the hive runtime
      const allAgents: DiscoverEntry[] = Object.entries(discoverResult)
        .filter(([category]) => category !== "Framework")
        .flatMap(([, entries]) => entries);

      const liveSessionMap = new Map<string, string>();
      for (const s of sessionsResult.sessions) {
        liveSessionMap.set(s.agent_path.replace(/\/$/, ""), s.session_id);
      }

      const unreadCounts = loadJson<Record<string, number>>(UNREAD_KEY, {});

      const newColonies: Colony[] = allAgents.map((agent) => {
        const slug = agentSlug(agent.path);
        const colonyId = slugToColonyId(slug);
        const normalizedPath = agent.path.replace(/\/$/, "");
        const sessionId = liveSessionMap.get(normalizedPath) ?? null;
        const isRunning = sessionId !== null;

        return {
          id: colonyId,
          name: agent.name || slugToDisplayName(slug),
          agentPath: agent.path,
          description: agent.description,
          status: isRunning ? "running" : "idle",
          unreadCount: unreadCounts[colonyId] ?? 0,
          queenId: slug,
          sessionId,
          sessionCount: agent.session_count,
          runCount: agent.run_count,
        };
      });

      // Build queens from backend profiles (not derived from colonies)
      const liveQueenIds = new Set(
        sessionsResult.sessions
          .filter((s) => s.queen_id)
          .map((s) => s.queen_id as string),
      );

      const newQueens: QueenBee[] = queenProfilesResult.queens.map((qp) => ({
        id: qp.id,
        name: qp.name,
        role: qp.title,
        status: liveQueenIds.has(qp.id) ? "online" : "offline",
      }));

      setColonies(newColonies);
      setQueens(newQueens);
    } catch {
      // Silently fail — colonies will be empty
    } finally {
      setLoading(false);
    }
  }, []);

  // Lightweight status poll: /sessions only — updates running/idle status
  // on existing colonies without re-scanning the filesystem.
  const fetchStatus = useCallback(async () => {
    try {
      const { sessions } = await sessionsApi.list();
      const livePathSet = new Set(
        sessions.map((s) => s.agent_path.replace(/\/$/, "")),
      );
      setColonies((prev) =>
        prev.map((c) => {
          const normalizedPath = c.agentPath.replace(/\/$/, "");
          const isRunning = livePathSet.has(normalizedPath);
          const sessionId =
            sessions.find((s) => s.agent_path.replace(/\/$/, "") === normalizedPath)
              ?.session_id ?? null;
          return { ...c, status: isRunning ? "running" : "idle", sessionId };
        }),
      );
      setQueens((prev) =>
        prev.map((q) => {
          const colony = coloniesRef.current.find((c) => c.queenId === q.id);
          if (!colony) return q;
          const normalizedPath = colony.agentPath.replace(/\/$/, "");
          const isRunning = livePathSet.has(normalizedPath);
          return { ...q, status: isRunning ? "online" : "offline" };
        }),
      );
    } catch {
      // Silently fail
    }
  }, []);

  const deleteColony = useCallback(async (colonyId: string) => {
    const colony = coloniesRef.current.find((c) => c.id === colonyId);
    if (!colony) return;
    // Optimistically remove from UI
    setColonies((prev) => prev.filter((c) => c.id !== colonyId));
    setQueens((prev) => prev.filter((q) => q.colonyId !== colonyId));
    // Delete on backend (fire-and-forget)
    agentsApi.deleteAgent(colony.agentPath).catch(() => {});
  }, []);

  const refresh = useCallback(() => {
    fetchColonies();
  }, [fetchColonies]);

  // Full fetch on mount
  useEffect(() => {
    fetchColonies();
  }, [fetchColonies]);

  // Lightweight status poll every 30s
  useEffect(() => {
    const id = setInterval(fetchStatus, 30_000);
    return () => clearInterval(id);
  }, [fetchStatus]);

  // Full fetch on tab visibility change
  useEffect(() => {
    const handler = () => {
      if (document.visibilityState === "visible") fetchColonies();
    };
    document.addEventListener("visibilitychange", handler);
    return () => document.removeEventListener("visibilitychange", handler);
  }, [fetchColonies]);

  return (
    <ColonyContext.Provider
      value={{
        colonies,
        queens,
        loading,
        sidebarCollapsed,
        setSidebarCollapsed,
        userProfile,
        setUserProfile,
        markVisited,
        deleteColony,
        refresh,
      }}
    >
      {children}
    </ColonyContext.Provider>
  );
}
