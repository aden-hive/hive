import { createContext, useCallback, useContext, useMemo, useState } from "react";
import type { ReactNode } from "react";

/**
 * Cross-page hook for opening the sidebar's Create Colony modal with
 * prefilled values. The modal itself still lives inside Sidebar — this
 * context just exposes a "request" channel so other pages (Prompt
 * Library, etc.) can fire it without duplicating the form UI.
 *
 * Usage:
 *   const { openCreateColony } = useCreateColony();
 *   openCreateColony({ name: "my_team", goal: "Do the thing.", queenId: "queen_growth" });
 *
 * The Sidebar consumes ``pendingRequest`` to seed its local form state
 * once, then calls ``clearRequest()`` so the prefill doesn't reapply on
 * subsequent renders.
 */
export interface CreateColonyRequest {
  name?: string;
  goal?: string;
  /**
   * Queen to pre-select in the modal. Derived from the originating prompt's
   * category (see ``categoryToQueen``). Ignored if the user doesn't have that
   * queen active — the Sidebar validates before seeding.
   */
  queenId?: string;
}

interface CreateColonyContextValue {
  pendingRequest: CreateColonyRequest | null;
  openCreateColony: (req?: CreateColonyRequest) => void;
  clearRequest: () => void;
}

const CreateColonyContext = createContext<CreateColonyContextValue | null>(null);

export function CreateColonyProvider({ children }: { children: ReactNode }) {
  const [pendingRequest, setPendingRequest] = useState<CreateColonyRequest | null>(null);

  const openCreateColony = useCallback((req: CreateColonyRequest = {}) => {
    setPendingRequest(req);
  }, []);

  const clearRequest = useCallback(() => {
    setPendingRequest(null);
  }, []);

  const value = useMemo<CreateColonyContextValue>(
    () => ({ pendingRequest, openCreateColony, clearRequest }),
    [pendingRequest, openCreateColony, clearRequest],
  );

  return <CreateColonyContext.Provider value={value}>{children}</CreateColonyContext.Provider>;
}

export function useCreateColony(): CreateColonyContextValue {
  const ctx = useContext(CreateColonyContext);
  if (!ctx) throw new Error("useCreateColony() called outside <CreateColonyProvider>");
  return ctx;
}
