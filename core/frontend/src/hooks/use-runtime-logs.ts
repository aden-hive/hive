import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/api/client";

export interface RuntimeLogEntry {
  seq: number;
  stream: "stdout" | "stderr";
  text: string;
}

interface RuntimeLogsPayload {
  boot: string;
  entries: RuntimeLogEntry[];
}

const MAX_LINES = 500;
const POLL_MS = 2_000;

/**
 * The Hive server's recent log (``GET /api/runtime-logs``), polled while
 * ``enabled``. Polling, not a stream: every open stream holds one of the
 * browser's few same-origin connections (see BrowserStatusBadge). ``clear``
 * hides what is shown so far; new lines keep coming.
 */
export function useRuntimeLogs(enabled: boolean) {
  const [logs, setLogs] = useState<RuntimeLogEntry[]>([]);
  const cursor = useRef({ boot: "", after: 0 });

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const poll = async () => {
      const { boot, after } = cursor.current;
      try {
        const res = await api.get<RuntimeLogsPayload>(
          `/runtime-logs?after=${after}&boot=${encodeURIComponent(boot)}`,
        );
        if (cancelled) return;
        // A new boot means the server restarted and sent its whole buffer.
        const restarted = res.boot !== boot;
        const last = res.entries[res.entries.length - 1];
        cursor.current = { boot: res.boot, after: last ? last.seq : restarted ? 0 : after };
        if (restarted || res.entries.length > 0) {
          setLogs((prev) => (restarted ? res.entries : [...prev, ...res.entries]).slice(-MAX_LINES));
        }
      } catch {
        // Runtime unreachable: the connectivity banner says so; try again next tick.
      }
    };
    void poll();
    const timer = setInterval(() => void poll(), POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [enabled]);

  const clear = useCallback(() => setLogs([]), []);
  return { logs, clear };
}
