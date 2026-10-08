// Aligns with LiveSession.queen_phase. The colony page boots in "colony"
// phase whenever it's resuming a forked queen session; the queen-DM enters
// the suggestion flow but never persists in any intermediate phase.
export type ColonyRestorePhase = "independent" | "colony";

export function shouldUsePrefetchedColonyRestore(
  prefetchedSessionId: string | undefined,
  resolvedSessionId: string,
): boolean {
  return !!prefetchedSessionId && prefetchedSessionId === resolvedSessionId;
}

export function resolveInitialColonyPhase({
  prefetchedSessionId,
  resolvedSessionId,
  prefetchedPhase,
  serverPhase,
  hasWorker,
}: {
  prefetchedSessionId: string | undefined;
  resolvedSessionId: string;
  prefetchedPhase: ColonyRestorePhase | null;
  serverPhase: ColonyRestorePhase | undefined;
  hasWorker: boolean;
}): ColonyRestorePhase {
  const restoredPhase = shouldUsePrefetchedColonyRestore(
    prefetchedSessionId,
    resolvedSessionId,
  )
    ? prefetchedPhase
    : null;
  return restoredPhase || serverPhase || (hasWorker ? "colony" : "independent");
}
