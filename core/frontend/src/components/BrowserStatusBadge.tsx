import { useState, useEffect } from "react";

type BridgeStatus = "checking" | "connected" | "disconnected" | "offline";

const BRIDGE_STATUS_STREAM_URL = "/api/browser/status/stream";

export default function BrowserStatusBadge() {
  const [status, setStatus] = useState<BridgeStatus>("checking");

  useEffect(() => {
    const es = new EventSource(BRIDGE_STATUS_STREAM_URL);

    es.addEventListener("status", (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data) as {
          bridge: boolean;
          connected: boolean;
        };
        if (!data.bridge) setStatus("offline");
        else setStatus(data.connected ? "connected" : "disconnected");
      } catch {
        setStatus("offline");
      }
    });

    // EventSource auto-reconnects on transient errors; the next
    // successful ``status`` event will overwrite this. We only flip
    // to "offline" so the badge doesn't get stuck on "connected"
    // after a backend restart.
    es.onerror = () => setStatus("offline");

    return () => es.close();
  }, []);

  if (status === "checking") return null;

  const label =
    status === "connected"
      ? "Browser connected"
      : status === "disconnected"
        ? "Extension not connected"
        : "Browser offline";

  const dotClass =
    status === "connected"
      ? "bg-green-500"
      : status === "disconnected"
        ? "bg-yellow-500"
        : "bg-muted-foreground/40";

  return (
    <div
      className="flex items-center gap-1.5 text-xs select-none"
      title={label}
    >
      <span className="relative flex h-2 w-2 flex-shrink-0">
        {status === "connected" && (
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-60" />
        )}
        <span className={`relative inline-flex rounded-full h-2 w-2 ${dotClass}`} />
      </span>
      <span className="text-muted-foreground hidden sm:inline">Browser</span>
    </div>
  );
}
