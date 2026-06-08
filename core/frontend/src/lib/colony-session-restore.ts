// "incubating" is queen-DM-only; the colony page never enters it (the queen
// auto-switches back to independent before the lock fires). Keep it in the
// union so the type lines up with LiveSession.queen_phase.
export type ColonyRestorePhase =
  | "independent"
  | "incubating"
  | "working"
  | "reviewing";

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
  return restoredPhase || serverPhase || (hasWorker ? "working" : "reviewing");
}
