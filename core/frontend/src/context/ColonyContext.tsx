import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useMemo,
  useRef,
  type ReactNode,
} from "react";
import type { Colony, QueenBee, QueenProfileSummary, UserProfile } from "@/types/colony";
import type { PortraitDescriptor } from "@/api/queens";
import type { DiscoverEntry, LiveSession } from "@/api/types";
import { agentsApi } from "@/api/agents";
import { coloniesApi } from "@/api/colonies";
import { sessionsApi } from "@/api/sessions";
import { queensApi } from "@/api/queens";
import { configApi } from "@/api/config";
import { useMe } from "@/lib/me";
import { leaderById } from "@/lib/queen-leaders";
import {
  agentSlug,
  slugToColonyId,
  slugToDisplayName,
  COLONY_DISPLAY_NAME_OVERRIDES,
} from "@/lib/colony-registry";
import { userStorage } from "@/lib/userStorage";

// ── per-user storage keys (resolved against userStorage namespace) ─────────

const SIDEBAR_KEY = "sidebar-collapsed";
const UNREAD_KEY = "unread-counts";
const LAST_VISIT_KEY = "colony-last-visit";

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
  deleteColony: (colonyId: string, purge?: boolean) => Promise<void>;
  /** Refresh colony data from the server */
  refresh: () => void;
  /** Cache-busting version for user avatar — bump after upload */
  userAvatarVersion: number;
  bumpUserAvatar: () => void;
  /** Whether an avatar file exists on disk for the current user. Used to
   *  gate the `<img>` load so first-time users don't see a 404. */
  userHasAvatar: boolean;
  /** Per-queen cache-bust counter. Bump after a queen's avatar is uploaded so
   *  every renderer (org chart, sidebar, chat panel) requests the new image. */
  queenAvatarVersion: (queenId: string) => number;
  bumpQueenAvatar: (queenId: string) => void;
  /** Whether an avatar file exists on disk for a given queen. Used to gate
   *  the `<img>` load so users without uploaded avatars don't see 404s. */
  queenHasAvatar: (queenId: string) => boolean;
}

const ColonyContext = createContext<ColonyContextValue | null>(null);

export function useColony(): ColonyContextValue {
  const ctx = useContext(ColonyContext);
  if (!ctx) throw new Error("useColony must be used within ColonyProvider");
  return ctx;
}

// ── Provider ─────────────────────────────────────────────────────────────────

export function ColonyProvider({ children }: { children: ReactNode }) {
  const { me } = useMe();
  const [colonies, setColonies] = useState<Colony[]>([]);
  const [queens, setQueens] = useState<QueenBee[]>([]);
  const [rawQueenProfiles, setRawQueenProfiles] = useState<QueenProfileSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [sidebarCollapsed, _setSidebarCollapsed] = useState(() =>
    userStorage.get<boolean>(SIDEBAR_KEY, false),
  );
  // displayName/about are sourced authoritatively from /config/profile (the
  // user-scoped runtime). The localStorage cache used to live here under
  // hive:user-profile, but now that ColonyProvider mounts behind both
  // RuntimeProvider and the AuthGate user-key boundary, the runtime call
  // resolves before we render anything that depends on the profile, so a
  // local cache is redundant.
  const [userProfile, _setUserProfile] = useState<UserProfile>({
    displayName: "",
    about: "",
  });
  const [, setLastVisit] = useState<Record<string, number>>(() =>
    userStorage.get<Record<string, number>>(LAST_VISIT_KEY, {}),
  );

  const [userAvatarVersion, setUserAvatarVersion] = useState(0);
  const [userHasAvatar, setUserHasAvatar] = useState(false);
  // Bumping the cache-bust version always means a fresh upload completed,
  // so flip ``userHasAvatar`` true to make the renderer attempt the load.
  const bumpUserAvatar = useCallback(() => {
    setUserAvatarVersion((v) => v + 1);
    setUserHasAvatar(true);
  }, []);

  const [queenAvatarVersions, setQueenAvatarVersions] = useState<Record<string, number>>({});
  const [queenHasAvatarMap, setQueenHasAvatarMap] = useState<Record<string, boolean>>({});
  const queenAvatarVersion = useCallback(
    (queenId: string) => queenAvatarVersions[queenId] ?? 0,
    [queenAvatarVersions],
  );
  const queenHasAvatar = useCallback(
    (queenId: string) => queenHasAvatarMap[queenId] ?? false,
    [queenHasAvatarMap],
  );
  const bumpQueenAvatar = useCallback((queenId: string) => {
    setQueenAvatarVersions((prev) => ({
      ...prev,
      [queenId]: (prev[queenId] ?? 0) + 1,
    }));
    setQueenHasAvatarMap((prev) => ({ ...prev, [queenId]: true }));
  }, []);

  // "Pushed to workspace" was a cloud feature (removed). In local mode no
  // colony is pushed to a remote VM, so these are inert: nothing is ever
  // pinned and every colony lives locally.
  const isPushed = useCallback((_slug: string) => false, []);
  const pushed = useMemo<Set<string>>(() => new Set<string>(), []);

  const coloniesRef = useRef<Colony[]>(colonies);
  useEffect(() => {
    coloniesRef.current = colonies;
  }, [colonies]);

  const setSidebarCollapsed = useCallback((v: boolean) => {
    _setSidebarCollapsed(v);
    userStorage.set(SIDEBAR_KEY, v);
  }, []);

  const setUserProfile = useCallback((p: UserProfile) => {
    _setUserProfile(p);
    configApi.setProfile(p.displayName, p.about).catch(() => {});
  }, []);


  const markVisited = useCallback((colonyId: string) => {
    setLastVisit((prev) => {
      const next = { ...prev, [colonyId]: Date.now() };
      userStorage.set(LAST_VISIT_KEY, next);
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
        // A dead local runtime (runtime_not_ready) must not take down the
        // entire list — backend-pinned colonies still need to render.
        // Fall back to an empty discover; the splice-in below ensures
        // every pinned colony from PushedColoniesContext appears anyway.
        agentsApi.discover().catch(() => ({})),
        sessionsApi.list().catch(() => ({ sessions: [] as LiveSession[] })),
        queensApi.list().catch(() => ({ queens: [] as QueenProfileSummary[] })),
        sessionsApi.history().catch(() => ({ sessions: [] as { agent_path?: string | null; queen_id?: string | null; created_at?: number; last_active_at?: number }[] })),
      ]);

      // Skip "Framework" agents — those are internal to the hive runtime
      const allAgents: DiscoverEntry[] = Object.entries(discoverResult)
        .filter(([category]) => category !== "Framework")
        .flatMap(([, entries]) => entries);

      // Pinned colonies are DEFINITIVE — backend's
      // `account_vm_pushed_colonies` says these belong in the sidebar,
      // period. Render them regardless of whether the workspace VM is
      // live, regardless of whether local hive-serve responded to
      // /discover, regardless of any other race. `pushed` arrives via
      // PushedColoniesContext, which has its own backend fetch on mount
      // + subscribes to hive:pushed-colonies-changed for live updates.
      // No waiting on /v1/workspace/start, no augment-in-main-process,
      // no event-coupled refetch dance. The fetchColonies useCallback
      // already lists `pushed` (and thus `isPushed`) as a dep, so an
      // updated pin set automatically triggers a refresh.
      const presentSlugs = new Set(
        allAgents.map((a) => agentSlug(a.path)).filter(Boolean),
      );
      for (const slug of pushed) {
        if (!slug || presentSlugs.has(slug)) continue;
        allAgents.push({
          path: `/root/.hive/colonies/${slug}`,
          name: "",
          description: "",
          category: "Your Agents",
          session_count: 0,
          run_count: 0,
          node_count: 0,
          tool_count: 0,
          tags: [],
          last_active: null,
          created_at: null,
          icon: null,
          is_loaded: false,
          workers: [],
        });
        presentSlugs.add(slug);
      }

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

      const unreadCounts = userStorage.get<Record<string, number>>(UNREAD_KEY, {});

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
          // Override wins over the runtime's title-cased slug name (e.g. so
          // `icp_outreach` brands as "ICP Outreach" rather than "Icp Outreach").
          name: COLONY_DISPLAY_NAME_OVERRIDES[slug] || agent.name || slugToDisplayName(slug),
          agentPath: agent.path,
          description: agent.description,
          status: isRunning ? "active" : "idle",
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

      // Discover can surface the same colony twice — e.g. a colony that lives
      // locally AND is pinned to the workspace VM, when the local and pushed
      // sources disagree on the slug spelling. Both map to the same colony id
      // here, so collapse by id (first wins: the local entry, emitted before
      // any VM-synthesized one, carries the real metadata). Guards the sidebar
      // against React "duplicate key" warnings and doubled cards.
      const seenColonyIds = new Set<string>();
      const dedupedColonies = newColonies.filter((c) => {
        if (seenColonyIds.has(c.id)) return false;
        seenColonyIds.add(c.id);
        return true;
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

      setColonies(dedupedColonies);
      setQueens(newQueens);
      setRawQueenProfiles(sortedQueens);
      // Refresh the queen has_avatar map from the listing — preserve any
      // ``true`` flags set locally by a recent upload that may not yet be
      // reflected on disk by the time this listing was generated.
      setQueenHasAvatarMap((prev) => {
        const next: Record<string, boolean> = { ...prev };
        for (const qp of sortedQueens) {
          if (qp.has_avatar) next[qp.id] = true;
          else if (next[qp.id] !== true) next[qp.id] = false;
        }
        return next;
      });
    } catch {
      // Silently fail — colonies will be empty
    } finally {
      setLoading(false);
    }
    // `pushed` is included so a push/unpin done during this session
    // (PushedColoniesContext fires hive:pushed-colonies-changed →
    // PushedColoniesProvider updates the Set → new identity here)
    // triggers a fresh fetchColonies, immediately surfacing the new
    // pin in the sidebar.
  }, [pushed]);

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
          return { ...c, status: sessionId ? "active" : "idle", sessionId };
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

  const deleteColony = useCallback(async (colonyId: string, purge = false) => {
    const colony = coloniesRef.current.find((c) => c.id === colonyId);
    if (!colony) return;
    const slug = agentSlug(colony.agentPath);
    // Optimistically remove from UI
    setColonies((prev) => prev.filter((c) => c.id !== colonyId));
    setQueens((prev) => prev.filter((q) => q.colonyId !== colonyId));
    // Delete via the colony route. The colony slug sits in the URL path, so the
    // request routes to the workspace VM for pushed colonies and to the local
    // runtime otherwise — hitting whichever runtime owns the files. purge=false
    // is a soft delete (data kept on disk); purge=true removes it.
    try {
      await coloniesApi.delete(slug, purge);
    } catch {
      // Deletion failed — re-fetch below restores the colony in the UI.
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
        _setUserProfile({ displayName: p.displayName, about: p.about });
      }
      // Only flip ``userHasAvatar`` true when the runtime confirms a file
      // exists. We deliberately don't reset to ``false`` here — a recent
      // upload may have already bumped the version locally.
      if (p.has_avatar) setUserHasAvatar(true);
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

  // The user's onboarding-chosen lead per queen (name/portrait) is the
  // source of truth for the persona. The runtime queen profile is *supposed*
  // to be patched to match on first run, but when the lead was picked on the
  // signup site the desktop runtime often still holds the default persona —
  // so the profile and the preference disagree, surfacing a queen's real name
  // over the default lead's face. Overlay the preference here, once, so
  // every consumer (DM, sidebar, org chart, colonies) reads one consistent
  // persona. Resolves the full descriptor from the leader catalog by the
  // stored lead id, since the preference itself may only carry the id + name.
  // Title stays with the runtime profile — the catalog's `t` is an org
  // affiliation ("LVMH"), not a function.
  const resolvePersona = useCallback(
    <T extends { name: string; title: string; portrait?: PortraitDescriptor | null }>(
      queenId: string,
      fallback: T,
    ): { name: string; title: string; portrait: PortraitDescriptor | null } => {
      const pref = me?.preferences?.queens?.[queenId];
      if (!pref) {
        return { name: fallback.name, title: fallback.title, portrait: fallback.portrait ?? null };
      }
      const lead = pref.id ? leaderById(queenId, pref.id) : undefined;
      return {
        name: lead?.n ?? pref.n ?? fallback.name,
        title: fallback.title,
        portrait:
          lead?.p ?? (pref.p as PortraitDescriptor | null | undefined) ?? fallback.portrait ?? null,
      };
    },
    [me?.preferences?.queens],
  );

  const queenProfiles = useMemo<QueenProfileSummary[]>(
    () =>
      rawQueenProfiles.map((qp) => {
        const persona = resolvePersona(qp.id, qp);
        return { ...qp, name: persona.name, title: persona.title, portrait: persona.portrait };
      }),
    [rawQueenProfiles, resolvePersona],
  );

  const resolvedQueens = useMemo<QueenBee[]>(
    () =>
      queens.map((q) => {
        const persona = resolvePersona(q.id, { name: q.name, title: q.role });
        return { ...q, name: persona.name, role: persona.title };
      }),
    [queens, resolvePersona],
  );

  return (
    <ColonyContext.Provider
      value={{
        colonies,
        queens: resolvedQueens,
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
        userHasAvatar,
        queenAvatarVersion,
        bumpQueenAvatar,
        queenHasAvatar,
      }}
    >
      {children}
    </ColonyContext.Provider>
  );
}
