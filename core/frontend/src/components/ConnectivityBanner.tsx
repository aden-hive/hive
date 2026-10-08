import { useEffect, useState } from "react";
import { WifiOff, AlertTriangle, X } from "lucide-react";
import { useConnectivityStatus } from "@/hooks/use-connectivity-status";

/**
 * Slim top-of-app banner that appears only when the renderer can't
 * reach the runtime, or when navigator reports the OS is offline. A
 * tiny dismiss button lets the user hide it; we re-show automatically
 * if a *fresh* connectivity issue starts after dismissal.
 *
 * Designed to occupy minimal space and not push other layout —
 * 28-px-tall fixed-position bar at the top, transparent enough to
 * sit above any page header.
 */
export default function ConnectivityBanner() {
  const { status, detail, since } = useConnectivityStatus();
  // Track which "issue" instance the user dismissed, keyed by ``since``.
  // A new ``since`` (different timestamp) = fresh issue → un-dismiss.
  const [dismissedSince, setDismissedSince] = useState<number | null>(null);
  const [, setTick] = useState(0);

  // Re-render once a second so the elapsed counter ticks up.
  useEffect(() => {
    if (status === "online") return;
    const id = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [status]);

  if (status === "online") return null;
  if (since !== null && since === dismissedSince) return null;

  const isOffline = status === "offline";
  const Icon = isOffline ? WifiOff : AlertTriangle;
  const colorClass = isOffline
    ? "bg-red-600 text-white"
    : "bg-amber-500 text-white";

  const ageS = since ? Math.max(0, Math.floor((Date.now() - since) / 1000)) : 0;
  const ageLabel = ageS >= 60 ? `${Math.floor(ageS / 60)}m ${ageS % 60}s` : `${ageS}s`;

  return (
    <div
      role="status"
      aria-live="polite"
      className={`fixed top-0 inset-x-0 z-50 h-7 px-4 flex items-center gap-2 text-[12px] font-medium shadow ${colorClass}`}
    >
      <Icon className="w-3.5 h-3.5 flex-shrink-0" />
      <span className="truncate flex-1">
        {detail ?? (isOffline ? "Offline" : "Connectivity issues")}
      </span>
      {since && (
        <span className="opacity-75 tabular-nums hidden sm:inline">
          {ageLabel}
        </span>
      )}
      <button
        type="button"
        onClick={() => setDismissedSince(since)}
        className="opacity-75 hover:opacity-100 transition-opacity"
        aria-label="Dismiss"
        title="Dismiss (re-shows on a fresh issue)"
      >
        <X className="w-3.5 h-3.5" />
      </button>
    </div>
  );
}
