import { useState, useEffect } from "react";

type BridgeStatus = "checking" | "connected" | "disconnected" | "offline";

const BRIDGE_STATUS_URL = "/api/browser/status";
const POLL_INTERVAL_MS = 3000;

export default function BrowserStatusBadge() {
  const [status, setStatus] = useState<BridgeStatus>("checking");

  useEffect(() => {
    let cancelled = false;

    const check = async () => {
      try {
        const res = await fetch(BRIDGE_STATUS_URL, {
          signal: AbortSignal.timeout(2000),
        });
        if (cancelled) return;
        if (res.ok) {
          const data = await res.json();
          setStatus(data.connected ? "connected" : "disconnected");
        } else {
          setStatus("offline");
        }
      } catch {
        if (!cancelled) setStatus("offline");
      }
    };

    check();
    const timer = setInterval(check, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
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
