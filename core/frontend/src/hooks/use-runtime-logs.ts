import { useCallback, useState } from "react";

// Kept for callers that still reference the entry shape.
export interface RuntimeLogEntry {
  seq: number;
  stream: "stdout" | "stderr";
  text: string;
}

/**
 * In the desktop shell this streamed the main-process runtime log ring
 * buffer over IPC. The web SPA has no such stream (the runtime is a remote
 * HTTP service), so this is a no-op that always reports an empty log.
 */
export function useRuntimeLogs() {
  const [logs] = useState<RuntimeLogEntry[]>([]);
  const clear = useCallback(() => {}, []);
  return { logs, clear };
}
