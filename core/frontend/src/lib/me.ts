/**
 * Local, cloud-free replacement for the former `@/context/MeContext`.
 *
 * The desktop build consolidated a `/v1/me` cloud payload (account,
 * subscription, credit balance) with per-user queen preferences and persisted
 * everything to the cloud. In the OSS web SPA there is no account/billing
 * surface, so `user`, `subscription`, and `balance` are always `null` and any
 * UI that depended on them is removed. The one piece worth keeping is the
 * per-queen preference map (decommissioned flags, org-chart positions, and the
 * chosen lead persona) — a legitimately local feature. It is stored in
 * `localStorage` here, with a provider-free external store so any component can
 * read and mutate it via the same hook API the old context exposed.
 */

import { useCallback, useMemo, useState, useSyncExternalStore } from "react";
import { queensApi, type PortraitDescriptor } from "@/api/queens";
import {
  DEFAULT_ACTIVE_QUEEN_IDS,
  DEFAULT_HIDDEN_QUEEN_IDS,
} from "@/lib/colony-registry";

export type SubscriptionStatus =
  | "active"
  | "trialing"
  | "past_due"
  | "canceled"
  | "incomplete"
  | "incomplete_expired"
  | "unpaid";

/** Per-queen override (lead persona, decommission flag, org-chart position). */
export interface MeQueenOverride {
  n?: string | null;
  bio?: string | null;
  id?: string | null;
  t?: string | null;
  p?: PortraitDescriptor | Record<string, unknown> | null;
  decommissioned?: boolean | null;
  pos?: { x: number; y: number } | null;
  [k: string]: unknown;
}

export interface MePreferences {
  theme?: string | null;
  density?: string | null;
  queens?: Record<string, MeQueenOverride> | null;
  [k: string]: unknown;
}

export interface MeUser {
  email?: string | null;
  full_name?: string | null;
  [k: string]: unknown;
}

export interface MeSnapshot {
  user: MeUser | null;
  preferences: MePreferences | null;
  subscription: null;
  balance: null;
}

// --- localStorage-backed queen-preference store -------------------------

const STORAGE_KEY = "hive.queenPrefs";

function readQueensMap(): Record<string, MeQueenOverride> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" ? (parsed as Record<string, MeQueenOverride>) : {};
  } catch {
    return {};
  }
}

// Cached snapshot so `useSyncExternalStore`'s getSnapshot returns a stable
// reference between mutations (React bails on re-render when identity is equal).
let cachedSnapshot: MeSnapshot = buildSnapshot(readQueensMap());
const listeners = new Set<() => void>();

function buildSnapshot(queens: Record<string, MeQueenOverride>): MeSnapshot {
  return {
    user: null,
    preferences: { queens },
    subscription: null,
    balance: null,
  };
}

function writeQueensMap(next: Record<string, MeQueenOverride>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    /* ignore quota/serialization errors — the in-memory snapshot still wins */
  }
  cachedSnapshot = buildSnapshot(next);
  for (const l of listeners) l();
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

function getSnapshot(): MeSnapshot {
  return cachedSnapshot;
}

// --- Pure selectors -----------------------------------------------------

/**
 * Whether LLM calls are permitted. The OSS runtime has no credit/billing
 * gate, so this is always true.
 */
export function canMakeLLMCalls(_me: MeSnapshot | null): boolean {
  return true;
}

function hasConfiguredQueens(me: MeSnapshot | null): boolean {
  const queens = me?.preferences?.queens;
  return !!queens && Object.keys(queens).length > 0;
}

/**
 * Pick the queen the user is most likely to want when a single "preferred"
 * queen is needed. First non-decommissioned configured queen (insertion
 * order), else a default-active queen present in the roster, else the static
 * default.
 */
export function resolvePreferredQueenId(
  me: MeSnapshot | null,
  availableQueenIds?: string[],
): string {
  const roster =
    availableQueenIds && availableQueenIds.length ? new Set(availableQueenIds) : null;
  const usable = (id: string) => !roster || roster.has(id);

  const queens = me?.preferences?.queens;
  if (queens) {
    const preferred = Object.keys(queens).find(
      (id) => !queens[id]?.decommissioned && usable(id),
    );
    if (preferred) return preferred;
  }
  const defaultActive = DEFAULT_ACTIVE_QUEEN_IDS.find(usable);
  if (defaultActive) return defaultActive;
  if (roster && availableQueenIds && availableQueenIds.length) {
    return availableQueenIds[0];
  }
  return DEFAULT_ACTIVE_QUEEN_IDS[0];
}

/** True iff this queen should be hidden from the active roster. */
export function isQueenDecommissioned(me: MeSnapshot | null, queenId: string): boolean {
  if (!hasConfiguredQueens(me)) {
    return !DEFAULT_ACTIVE_QUEEN_IDS.includes(queenId);
  }
  return !!me?.preferences?.queens?.[queenId]?.decommissioned;
}

/**
 * The default decommissioned seed to include on the first write to a user who
 * has no queen preferences yet, so making the map non-empty doesn't silently
 * re-activate the rest of the default-hidden set. Empty once prefs exist.
 */
function defaultHiddenSeed(
  me: MeSnapshot | null,
  exceptId: string,
): Record<string, { decommissioned: boolean }> {
  if (hasConfiguredQueens(me)) return {};
  return Object.fromEntries(
    DEFAULT_HIDDEN_QUEEN_IDS.filter((id) => id !== exceptId).map((id) => [
      id,
      { decommissioned: true },
    ]),
  );
}

// --- Hooks --------------------------------------------------------------

interface MeContextValue {
  me: MeSnapshot | null;
  refresh: () => Promise<MeSnapshot | null>;
  pendingCreditSpend: number;
  noteCreditSpend: (credits: number) => void;
}

/**
 * Read the local me snapshot. `refresh`/`noteCreditSpend` are no-ops kept for
 * call-site compatibility (there is no cloud account or credit ledger).
 */
export function useMe(): MeContextValue {
  const me = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const refresh = useCallback(async () => me, [me]);
  const noteCreditSpend = useCallback(() => {}, []);
  return useMemo(
    () => ({ me, refresh, pendingCreditSpend: 0, noteCreditSpend }),
    [me, refresh, noteCreditSpend],
  );
}

/**
 * Non-hook variant of `useQueenDecommission(id).setDecommissioned(false)` for
 * flows that only learn the queen id at runtime — e.g. right after creating a
 * custom queen, where a hook can't be called with the fresh id. Applies the
 * same first-write hidden seed so the rest of the default-hidden set stays
 * hidden.
 */
export function activateQueen(queenId: string): void {
  const current = readQueensMap();
  writeQueensMap({
    ...current,
    ...defaultHiddenSeed(getSnapshot(), queenId),
    [queenId]: { ...(current[queenId] ?? {}), decommissioned: false },
  });
}

/** Read + toggle a queen's decommissioned state (persisted locally). */
export function useQueenDecommission(queenId: string) {
  const me = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const isDecommissioned = isQueenDecommissioned(me, queenId);
  const [saving, setSaving] = useState(false);

  const setDecommissioned = useCallback(
    async (next: boolean) => {
      const current = readQueensMap();
      const existing = current[queenId] ?? {};
      setSaving(true);
      try {
        writeQueensMap({
          ...current,
          ...defaultHiddenSeed(getSnapshot(), queenId),
          [queenId]: { ...existing, decommissioned: next },
        });
      } finally {
        setSaving(false);
      }
    },
    [queenId],
  );

  return useMemo(
    () => ({ isDecommissioned, setDecommissioned, saving }),
    [isDecommissioned, setDecommissioned, saving],
  );
}

export interface QueenLeadInput {
  leaderId: string;
  name: string;
  title: string;
  bio: string;
  portrait: PortraitDescriptor;
}

/**
 * Assign a lead persona to a function-queen ("hire"). Persists the flat lead
 * descriptor locally AND writes name/summary/portrait to the runtime queen
 * profile so the org chart card and the queen's identity update.
 */
export function useSetQueenLead() {
  const [savingQueenId, setSavingQueenId] = useState<string | null>(null);

  const setLead = useCallback(
    async (queenId: string, lead: QueenLeadInput) => {
      if (savingQueenId) return;
      const current = readQueensMap();
      const existing = current[queenId] ?? {};
      setSavingQueenId(queenId);
      try {
        writeQueensMap({
          ...current,
          ...defaultHiddenSeed(getSnapshot(), queenId),
          [queenId]: {
            ...existing,
            id: lead.leaderId,
            n: lead.name,
            t: lead.title,
            bio: lead.bio,
            p: lead.portrait,
            decommissioned: false,
          },
        });
        try {
          await queensApi.updateProfile(queenId, {
            name: lead.name,
            summary: lead.bio,
            portrait: lead.portrait,
          });
        } catch (err) {
          console.error("[hire-lead] runtime profile update failed", err);
        }
      } finally {
        setSavingQueenId(null);
      }
    },
    [savingQueenId],
  );

  return useMemo(() => ({ setLead, savingQueenId }), [setLead, savingQueenId]);
}

/** Persist one queen card's org-chart position (locally). */
export function useSetQueenPosition() {
  return useCallback(async (queenId: string, pos: { x: number; y: number }) => {
    const current = readQueensMap();
    const existing = current[queenId] ?? {};
    writeQueensMap({
      ...current,
      ...defaultHiddenSeed(getSnapshot(), queenId),
      [queenId]: { ...existing, pos },
    });
  }, []);
}

/** Restore positions for several queens in one write (undo a reset). */
export function useSetQueenPositions() {
  return useCallback(
    async (positions: Record<string, { x: number; y: number }>) => {
      const ids = Object.keys(positions);
      if (ids.length === 0) return;
      const current = readQueensMap();
      const next: Record<string, MeQueenOverride> = {
        ...current,
        ...defaultHiddenSeed(getSnapshot(), ids[0]),
      };
      for (const id of ids) {
        next[id] = { ...(current[id] ?? {}), pos: positions[id] };
      }
      writeQueensMap(next);
    },
    [],
  );
}

/** Clear every queen's saved org-chart position (locally). */
export function useResetQueenPositions() {
  return useCallback(async () => {
    const current = readQueensMap();
    const next: Record<string, MeQueenOverride> = {};
    let changed = false;
    for (const [id, override] of Object.entries(current)) {
      if (override && override.pos != null) {
        const rest = { ...override };
        delete rest.pos;
        next[id] = rest;
        changed = true;
      } else {
        next[id] = override;
      }
    }
    if (!changed) return;
    writeQueensMap(next);
  }, []);
}
