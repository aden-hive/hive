export type ColonyRestorePhase = "independent" | "working" | "reviewing";

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
