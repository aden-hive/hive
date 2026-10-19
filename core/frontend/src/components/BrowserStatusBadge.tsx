import { useState, useEffect, useLayoutEffect, useRef } from "react";
import { Globe, Download } from "lucide-react";
import { api } from "@/api/client";
import { Tooltip } from "@/components/Tooltip";

// "stale" = bridge reports the extension is connected but the last app-level
// pong is older than ~15s, meaning the offscreen page or service worker is
// wedged. The bridge will close the WS once the ping-timeout fires; this state
// is the brief window between "looks connected" and "actually closed".
type BridgeStatus = "checking" | "connected" | "stale" | "disconnected" | "offline";

// Chrome Web Store listing for the Hive Browser Bridge extension.
// Clicking the disconnected badge opens this in the user's default
// browser via Electron's shell.openExternal IPC bridge.
export const BROWSER_EXT_STORE_URL =
  "https://chromewebstore.google.com/detail/hive-browser-bridge/jkpcegnbfimimjodblcemoheedidnppm";

interface ActiveTab {
  id?: number | null;
  title?: string | null;
  url?: string | null;
}

// Scrolls long tab titles horizontally (carousel) when they overflow the
// cramped header chip; renders plain text when they fit. Measures once per
// title: the viewport is content-sized but capped by `max-w`, so a title wider
// than the cap reports scrollWidth > clientWidth and flips into the two-copy
// marquee track that loops seamlessly (-50% == exactly one copy).
function TabMarquee({ text }: { text: string }) {
  const viewportRef = useRef<HTMLSpanElement>(null);
  const measureRef = useRef<HTMLSpanElement>(null);
  const [overflow, setOverflow] = useState(false);

  useLayoutEffect(() => {
    const vp = viewportRef.current;
    const m = measureRef.current;
    if (!vp || !m) return;
    setOverflow(m.scrollWidth > vp.clientWidth + 1);
  }, [text]);

  if (!overflow) {
    return (
      <span ref={viewportRef} className="inline-block max-w-[150px] overflow-hidden align-middle">
        <span ref={measureRef} className="block whitespace-nowrap truncate">
          {text}
        </span>
      </span>
    );
  }

  // Speed ∝ length so long and short titles scroll at a comfortable pace.
  const durationS = Math.min(24, Math.max(7, text.length * 0.4));
  return (
    <span ref={viewportRef} className="inline-block max-w-[150px] overflow-hidden align-middle">
      <span className="inline-flex whitespace-nowrap animate-marquee" style={{ animationDuration: `${durationS}s` }}>
        <span ref={measureRef} className="pr-8">
          {text}
        </span>
        <span aria-hidden className="pr-8">
          {text}
        </span>
      </span>
    </span>
  );
}

interface BridgeStatusPayload {
  bridge: boolean;
  connected: boolean;
  health?: "healthy" | "stale" | "disconnected" | "offline";
  last_pong_age_ms?: number | null;
  extension_version?: string | null;
  // Present only when the stream is session-scoped (sessionId passed below).
  // null = the queen owns no browser context / has no focused tab right now.
  active_tab?: ActiveTab | null;
}

// Bare hostname (no www.) — used as the inline label when a tab has no title
// yet, and to keep the tooltip's url compact.
function hostnameOf(url?: string | null): string {
  if (!url) return "";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

// `sessionId` scopes the badge to one queen so it can show that queen's own
// active browser tab. Omitted (e.g. the global ColonyHeader badge) → the badge
// stays a plain connection indicator with no tab label.
export default function BrowserStatusBadge({ sessionId }: { sessionId?: string | null }) {
  const [status, setStatus] = useState<BridgeStatus>("checking");
  const [detail, setDetail] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<ActiveTab | null>(null);

  useEffect(() => {
    let cancelled = false;
    // Fresh slate when the viewed queen changes, so a previous session's tab
    // doesn't linger until the next poll lands.
    setActiveTab(null);

    const apply = (parsed: BridgeStatusPayload) => {
      if (!parsed.bridge) {
        setStatus("offline");
        setDetail("Bridge runtime offline");
        setActiveTab(null);
        return;
      }
      if (parsed.health === "stale") {
        setStatus("stale");
        setActiveTab(null);
        const ageS = parsed.last_pong_age_ms != null
          ? Math.round(parsed.last_pong_age_ms / 1000)
          : null;
        setDetail(ageS != null ? `Extension stale (no pong in ${ageS}s)` : "Extension stale");
        return;
      }
      if (parsed.connected) {
        setStatus("connected");
        setDetail(parsed.extension_version ? `Hive Bridge Extension v${parsed.extension_version}` : null);
        setActiveTab(parsed.active_tab ?? null);
      } else {
        setStatus("disconnected");
        setDetail("Click to install Hive Browser Bridge");
        setActiveTab(null);
      }
    };

    // Polling, not the SSE stream: every EventSource permanently occupies
    // one of the browser's ~6 same-origin HTTP/1.1 sockets, and this badge
    // was one of the standing streams that exhausted the pool (attachments
    // and fetches then queue behind it forever). A 15s badge latency is a
    // fine trade; the /stream endpoint remains for the desktop shell whose
    // IPC-based SSE is exempt from the connection cap.
    const poll = async () => {
      try {
        const parsed = await api.get<BridgeStatusPayload>(
          sessionId
            ? `/browser/status?session_id=${encodeURIComponent(sessionId)}`
            : "/browser/status",
        );
        if (!cancelled) apply(parsed);
      } catch {
        if (!cancelled) {
          setStatus("offline");
          setDetail(null);
          setActiveTab(null);
        }
      }
    };
    void poll();
    const timer = setInterval(() => void poll(), 15_000);

    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [sessionId]);

  if (status === "checking") return null;

  const isClickable = status === "disconnected" || status === "offline";
  const label =
    detail ??
    (status === "connected"
      ? "Browser connected"
      : status === "stale"
        ? "Extension stale"
        : status === "disconnected"
          ? "Click to install Hive Browser Bridge"
          : "Browser offline");

  const dotClass =
    status === "connected"
      ? "bg-green-500"
      : status === "stale"
        ? "bg-orange-500"
        : status === "disconnected"
          ? "bg-yellow-500"
          : "bg-muted-foreground/40";

  const handleClick = () => {
    if (!isClickable) return;
    window.open(BROWSER_EXT_STORE_URL, "_blank", "noopener");
  };

  // Extension missing: the browser features don't work at all until the user
  // installs the bridge, so this isn't a status — it's the primary thing to do.
  // Render a full call-to-action pill (not the calm icon) so it reads as an
  // action. Clicking opens the Chrome Web Store listing directly; previously we
  // pointed users at a chrome://extensions developer-mode flow, which only
  // works for unpacked dev builds — wrong for the published desktop app.
  if (status === "disconnected") {
    return (
      <Tooltip label="Install the Hive Browser Bridge extension">
        <button
          type="button"
          onClick={handleClick}
          aria-label="Install the Hive Browser Bridge extension (opens Chrome Web Store)"
          className="group inline-flex items-center gap-1.5 h-7 pl-2 pr-2.5 rounded-full border border-primary/25 bg-primary/10 text-[11px] font-medium text-primary hover:bg-primary/15 hover:border-primary/40 transition-colors"
        >
          <Download className="w-3.5 h-3.5 animate-download-bob" />
          Connect browser
        </button>
      </Tooltip>
    );
  }

  // Connected and we know which tab this queen is on: surface it inline so the
  // user can see "what is this queen looking at" at a glance. Title is the
  // primary label; fall back to the bare host when Chrome hasn't reported a
  // title yet. The full title + url live in the tooltip.
  const tabText = activeTab ? (activeTab.title?.trim() || hostnameOf(activeTab.url)) : "";
  if (status === "connected" && tabText) {
    const host = hostnameOf(activeTab?.url);
    const tabId = typeof activeTab?.id === "number" ? activeTab.id : null;
    const tabTooltip =
      activeTab?.title?.trim() && host
        ? `${activeTab.title.trim()} · ${host}`
        : activeTab?.title?.trim() || activeTab?.url || tabText;
    // Clicking jumps the user to the real Chrome tab + raises its window
    // (best-effort; the tab may have closed since the last status frame).
    const reveal = () => {
      if (tabId == null) return;
      // Ask the extension to focus the target tab inside the browser. (The
      // desktop shell also raised the native browser app over the Hive
      // window; the web SPA can't control other OS windows, so that step is
      // dropped.)
      void api
        .post<{ ok?: boolean; revealed?: boolean; browserApp?: string }>(
          "/browser/tab/reveal",
          { tab_id: tabId },
        )
        .catch((e) => console.warn("[browser-badge] reveal tab failed", e));
    };
    const clickable = tabId != null;
    const Pill: React.ElementType = clickable ? "button" : "div";
    return (
      <Tooltip label={clickable ? `${tabTooltip}  ·  Click to open in browser` : tabTooltip}>
        <Pill
          type={clickable ? "button" : undefined}
          onClick={clickable ? reveal : undefined}
          aria-label={clickable ? `Open browser tab: ${tabTooltip}` : `Browser tab: ${tabTooltip}`}
          className={`relative inline-flex items-center gap-1.5 h-7 pl-2 pr-2.5 rounded-full border border-border/60 bg-muted/40 text-[11px] font-medium text-muted-foreground select-none max-w-[200px] ${
            clickable ? "cursor-pointer hover:text-foreground hover:bg-muted/70 hover:border-border transition-colors" : ""
          }`}
        >
          <Globe className="w-3.5 h-3.5 flex-shrink-0" />
          <TabMarquee text={tabText} />
          <span className="relative flex h-2 w-2 flex-shrink-0">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-60" />
            <span className="relative inline-flex rounded-full h-2 w-2 ring-1 ring-card bg-green-500" />
          </span>
        </Pill>
      </Tooltip>
    );
  }

  const Wrapper: React.ElementType = isClickable ? "button" : "div";
  return (
    <Tooltip label={label}>
      <Wrapper
        type={isClickable ? "button" : undefined}
        onClick={isClickable ? handleClick : undefined}
        className={`relative w-7 h-7 rounded-md flex items-center justify-center text-muted-foreground select-none ${
          isClickable ? "cursor-pointer hover:text-foreground hover:bg-muted/60 transition-colors" : ""
        }`}
        aria-label={isClickable ? `${label} (opens Chrome Web Store)` : label}
      >
        <Globe className="w-4 h-4" />
        <span className="absolute bottom-0.5 right-0.5 flex h-2 w-2">
          {status === "connected" && (
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-60" />
          )}
          <span className={`relative inline-flex rounded-full h-2 w-2 ring-1 ring-card ${dotClass}`} />
        </span>
      </Wrapper>
    </Tooltip>
  );
}
