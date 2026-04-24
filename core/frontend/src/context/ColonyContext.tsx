import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useRef,
  type ReactNode,
} from "react";
import type { Colony, QueenBee, QueenProfileSummary, UserProfile } from "@/types/colony";
import type { DiscoverEntry, LiveSession } from "@/api/types";
import { agentsApi } from "@/api/agents";
import { sessionsApi } from "@/api/sessions";
import { queensApi } from "@/api/queens";
import { configApi } from "@/api/config";
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
  queenProfiles: QueenProfileSummary[];
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
  /** Cache-busting version for user avatar — bump after upload */
  userAvatarVersion: number;
  bumpUserAvatar: () => void;
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
  const [queenProfiles, setQueenProfiles] = useState<QueenProfileSummary[]>([]);
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

  const [userAvatarVersion, setUserAvatarVersion] = useState(0);
  const bumpUserAvatar = useCallback(() => setUserAvatarVersion((v) => v + 1), []);

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
    configApi.setProfile(p.displayName, p.about).catch(() => {});
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
      const [discoverResult, sessionsResult, queenProfilesResult, historyResult] = await Promise.all([
        agentsApi.discover(),
        sessionsApi.list().catch(() => ({ sessions: [] as LiveSession[] })),
        queensApi.list().catch(() => ({ queens: [] as QueenProfileSummary[] })),
        sessionsApi.history().catch(() => ({ sessions: [] as { agent_path?: string | null; queen_id?: string | null; created_at?: number; last_active_at?: number }[] })),
      ]);

      // Skip "Framework" agents — those are internal to the hive runtime
      const allAgents: DiscoverEntry[] = Object.entries(discoverResult)
        .filter(([category]) => category !== "Framework")
        .flatMap(([, entries]) => entries);

      // Map agent_path → session_id + queen_id from live sessions
      const liveSessionMap = new Map<string, { sessionId: string; queenId: string | null }>();
      for (const s of sessionsResult.sessions) {
        const slug = agentSlug(s.agent_path);
        if (slug) {
          liveSessionMap.set(slug, {
            sessionId: s.session_id,
            queenId: s.queen_id ?? null,
          });
        }
      }

      // Map agent_path → queen_id from history (most recent session wins)
      const historyQueenMap = new Map<string, string>();
      for (const s of historyResult.sessions) {
        if (s.agent_path && s.queen_id) {
          const slug = agentSlug(s.agent_path);
          if (slug && !historyQueenMap.has(slug)) {
            historyQueenMap.set(slug, s.queen_id);
          }
        }
      }

      // queen_id → max last_active_at across that queen's history sessions.
      // Used to sort the sidebar Queen Bees list by most recent conversation.
      const queenLastActive = new Map<string, number>();
      for (const s of historyResult.sessions) {
        if (!s.queen_id) continue;
        const ts = s.last_active_at ?? s.created_at ?? 0;
        const prev = queenLastActive.get(s.queen_id);
        if (prev === undefined || ts > prev) queenLastActive.set(s.queen_id, ts);
      }

      const unreadCounts = loadJson<Record<string, number>>(UNREAD_KEY, {});

      const newColonies: Colony[] = allAgents.map((agent) => {
        const slug = agentSlug(agent.path);
        const colonyId = slugToColonyId(slug);
        const liveInfo = liveSessionMap.get(slug);
        const sessionId = liveInfo?.sessionId ?? null;
        const isRunning = sessionId !== null;
        const queenName = agent.workers?.[0]?.queen_name || "";
        const queenProfileId = liveInfo?.queenId ?? historyQueenMap.get(slug) ?? (queenName || null);

        return {
          id: colonyId,
          name: agent.name || slugToDisplayName(slug),
          agentPath: agent.path,
          description: agent.description,
          status: isRunning ? "running" : "idle",
          unreadCount: unreadCounts[colonyId] ?? 0,
          queenId: slug,
          queenProfileId,
          sessionId,
          sessionCount: agent.session_count,
          runCount: agent.run_count,
          queenName,
          createdAt: agent.created_at ?? null,
          lastActive: agent.last_active ?? null,
          task: agent.workers?.[0]?.task || "",
          icon: agent.icon ?? null,
        };
      });

      // Build queens from backend profiles (not derived from colonies)
      const liveQueenIds = new Set(
        sessionsResult.sessions
          .filter((s) => s.queen_id)
          .map((s) => s.queen_id as string),
      );

      // Sort queens by most recent DM activity (newest first). Stable tiebreak
      // by original API order keeps no-history queens at the bottom and prevents
      // flicker between renders when timestamps tie.
      const sortedQueens = queenProfilesResult.queens
        .map((qp, idx) => ({ qp, idx, ts: queenLastActive.get(qp.id) ?? -Infinity }))
        .sort((a, b) => (b.ts - a.ts) || (a.idx - b.idx))
        .map((x) => x.qp);

      const newQueens: QueenBee[] = sortedQueens.map((qp) => ({
        id: qp.id,
        name: qp.name,
        role: qp.title,
        status: liveQueenIds.has(qp.id) ? "online" : "offline",
      }));

      setColonies(newColonies);
      setQueens(newQueens);
      setQueenProfiles(sortedQueens);
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
      const liveSlugMap = new Map<string, string>();
      for (const s of sessions) {
        const slug = agentSlug(s.agent_path);
        if (slug) liveSlugMap.set(slug, s.session_id);
      }
      setColonies((prev) =>
        prev.map((c) => {
          const slug = agentSlug(c.agentPath);
          const sessionId = liveSlugMap.get(slug) ?? null;
          return { ...c, status: sessionId ? "running" : "idle", sessionId };
        }),
      );
      const liveQueenIds = new Set(
        sessions.filter((s) => s.queen_id).map((s) => s.queen_id as string),
      );
      setQueens((prev) =>
        prev.map((q) => ({
          ...q,
          status: liveQueenIds.has(q.id) ? "online" : "offline",
        })),
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
    // Delete on backend, then re-fetch to confirm it's gone
    try {
      await agentsApi.deleteAgent(colony.agentPath);
    } catch {
      // Deletion failed — re-fetch to restore the colony in the UI
    }
    fetchColonies();
  }, [fetchColonies]);

  const refresh = useCallback(() => {
    fetchColonies();
  }, [fetchColonies]);

  // Full fetch on mount
  useEffect(() => {
    fetchColonies();
    configApi.getProfile().then((p) => {
      if (p.displayName || p.about) {
        _setUserProfile(p);
        localStorage.setItem(PROFILE_KEY, JSON.stringify(p));
      }
    }).catch(() => {});
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
        queenProfiles,
        loading,
        sidebarCollapsed,
        setSidebarCollapsed,
        userProfile,
        setUserProfile,
        markVisited,
        deleteColony,
        refresh,
        userAvatarVersion,
        bumpUserAvatar,
      }}
    >
      {children}
    </ColonyContext.Provider>
  );
}
