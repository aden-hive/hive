import { useState } from "react";
import {
  Bell,
  Loader2,
  Check,
  AlertCircle,
  ExternalLink,
  X,
} from "lucide-react";
import {
  sentinelApi,
  type SentinelCredentialStatus,
} from "@/api/sentinel";
import { credentialsApi } from "@/api/credentials";
import { useQueensAuthorizationPrompt } from "@/context/QueensAuthorizationPromptContext";
import { getProviderLogo } from "@/data/providerLogos";
import { ProviderLogo } from "@/components/ProviderLogo";

type Channel = "telegram" | "slack";

const CHANNELS: { id: Channel; name: string; blurb: string }[] = [
  {
    id: "telegram",
    name: "Telegram",
    blurb: "Get pinged on Telegram when a colony stalls — reply to keep it moving.",
  },
  {
    id: "slack",
    name: "Slack",
    blurb: "Get pinged in Slack when a colony stalls — reply in-thread to keep it moving.",
  },
];

function openExternal(url: string) {
  window.open(url, "_blank", "noopener");
}

const linkCls =
  "inline-flex items-center gap-0.5 text-primary hover:underline cursor-pointer";

/** Inline external link — opens in the user's regular browser via the
 *  preload bridge (Electron won't follow a plain <a target="_blank">). */
function Lnk({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <span className={linkCls} onClick={() => openExternal(href)}>
      {children} <ExternalLink className="w-2.5 h-2.5" />
    </span>
  );
}

/** Brand mark drawn from the shared provider-logo table so it matches the
 *  rest of the credentials UI. */
function ChannelLogo({ provider, size = 18 }: { provider: string; size?: number }) {
  const logo = getProviderLogo(provider);
  if (!logo) return <Bell className="text-muted-foreground" style={{ width: size, height: size }} />;
  return <ProviderLogo provider={provider} size={size} />;
}

function isConnected(creds: SentinelCredentialStatus | null, ch: Channel): boolean {
  if (!creds) return false;
  return ch === "telegram" ? creds.telegram.configured : creds.slack.bot && creds.slack.app;
}

/** Number of alert channels (Telegram, Slack) the page can offer. */
export const SENTINEL_CHANNEL_COUNT = CHANNELS.length;

/** How many alert channels currently have their global bot token connected. */
export function sentinelConnectedCount(creds: SentinelCredentialStatus | null): number {
  return CHANNELS.filter((c) => isConnected(creds, c.id)).length;
}

/**
 * Sentinel alert-channel cards for the Credentials page's "Builtin Connectors"
 * section. Sentinel tokens are account-global (one Telegram bot / Slack app,
 * shared by every colony), so connecting them belongs here next to the OAuth
 * connectors. The per-colony destination + on/off toggle stays in each colony's
 * Automations tab — this only handles the global token half (the modal says so).
 *
 * Renders bare grid-item cards (plus its connect modal) so the parent can drop
 * them straight into the shared connectors grid; it owns no section chrome.
 */
export default function SentinelConnectorsSection({
  creds,
  onReload,
}: {
  /** Global sentinel credential status, owned by the page so the header
   *  count and these cards stay in sync. */
  creds: SentinelCredentialStatus | null;
  /** Re-fetch the status after a successful connect. */
  onReload: () => void;
}) {
  const [modal, setModal] = useState<Channel | null>(null);

  return (
    <>
      {CHANNELS.map((c) => {
        const connected = isConnected(creds, c.id);
        return (
          <div
            key={c.id}
            className="rounded-lg border border-border/50 bg-card p-3 flex flex-col h-full min-h-[140px] transition-colors hover:border-border/80"
          >
            {/* Row 1 — logo + name + status. "Alerts" marks the connector
                type (mirrors the OAuth cards' type chip) so it reads correctly
                alongside them in the merged Builtin Connectors grid. */}
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <div className="w-7 h-7 rounded-md bg-muted/30 flex items-center justify-center flex-shrink-0">
                  <ChannelLogo provider={c.id} size={16} />
                </div>
                <h3 className="text-[13px] font-semibold text-foreground leading-tight truncate">
                  {c.name}
                </h3>
              </div>
              <span className="inline-flex items-center gap-1 text-[10px] font-medium tracking-wide flex-shrink-0">
                <span
                  className={
                    connected
                      ? "w-1.5 h-1.5 rounded-full bg-emerald-500"
                      : "w-1.5 h-1.5 rounded-full border border-muted-foreground/40"
                  }
                  aria-hidden
                />
                <span className={connected ? "text-emerald-600/90" : "text-muted-foreground/70"}>
                  {connected ? "Connected" : "Alerts"}
                </span>
              </span>
            </div>

            {/* Row 2 — description */}
            <p className="text-[10.5px] text-muted-foreground/80 mt-1.5 line-clamp-2 leading-snug [min-height:2lh]">
              {c.blurb}
            </p>

            <div className="flex-1" />
            <div className="border-t border-border/40 mt-2.5" aria-hidden />

            {/* Action row */}
            <div className="pt-2.5">
              <button
                onClick={() => setModal(c.id)}
                className="flex items-center gap-1.5 text-xs font-medium text-primary hover:text-primary/80 transition-colors"
              >
                {connected ? "Reconnect" : "Connect"}
                <span className="text-muted-foreground/50">›</span>
              </button>
            </div>
          </div>
        );
      })}

      {modal && (
        <ConnectModal
          channel={modal}
          connected={isConnected(creds, modal)}
          onClose={() => setModal(null)}
          onSaved={onReload}
        />
      )}
    </>
  );
}

// ===========================================================================
// Connect modal — global token connection only (no per-colony target).
// ===========================================================================

function ConnectModal({
  channel,
  connected,
  onClose,
  onSaved,
}: {
  channel: Channel;
  connected: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { suppressNext } = useQueensAuthorizationPrompt();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Set once a fresh connect succeeds in this session, so we can show the
  // "now finish in a colony" confirmation. Distinct from the `connected` prop,
  // which reflects what was already on file when the modal opened.
  const [doneLabel, setDoneLabel] = useState<string | null>(null);

  // Telegram
  const [tgToken, setTgToken] = useState("");
  // Slack
  const [slBotToken, setSlBotToken] = useState("");
  const [slAppToken, setSlAppToken] = useState("");

  const connectTelegram = async () => {
    if (!tgToken.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await credentialsApi.save("telegram", { bot_token: tgToken.trim() });
      const v = await sentinelApi.validateTelegram(tgToken.trim());
      if (!v.ok) {
        setError(v.error ?? "Invalid bot token");
        return;
      }
      setDoneLabel(v.bot_username ? `@${v.bot_username}` : (v.bot_name ?? "bot"));
      setTgToken("");
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const connectSlack = async () => {
    if (!slBotToken.trim() || !slAppToken.trim()) return;
    setBusy(true);
    setError(null);
    try {
      // Sentinel uses the Slack token only to send notifications — it isn't
      // granting queens Slack tools, so mute the queens-authorization dialog
      // that the global SSE listener would otherwise pop on connect.
      suppressNext("slack");
      await credentialsApi.save("slack", { access_token: slBotToken.trim() });
      await credentialsApi.save("slack_app", { access_token: slAppToken.trim() });
      const v = await sentinelApi.validateSlack(slBotToken.trim());
      if (!v.ok) {
        setError(v.error ?? "Invalid Slack token");
        return;
      }
      setDoneLabel(v.team ?? "workspace");
      setSlBotToken("");
      setSlAppToken("");
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div
        className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm"
        onClick={busy ? undefined : onClose}
      />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-md max-h-[88vh] flex flex-col pointer-events-auto">
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-border/60">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-muted/30 flex items-center justify-center">
                <ChannelLogo provider={channel} size={18} />
              </div>
              <h2 className="text-sm font-semibold text-foreground capitalize">
                Connect {channel}
              </h2>
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded-md hover:bg-muted/60 text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Body */}
          <div className="px-5 py-4 overflow-y-auto space-y-3">
            {doneLabel ? (
              <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3">
                <p className="text-xs text-foreground flex items-center gap-1.5">
                  <Check className="w-3.5 h-3.5 text-emerald-500 flex-shrink-0" />
                  Connected{channel === "slack" ? " to " : " as "}
                  <strong>{doneLabel}</strong>.
                </p>
                <p className="text-[11px] text-muted-foreground mt-2 leading-relaxed">
                  Next, open a colony's <span className="text-foreground">Automations</span> tab,
                  pick where to be pinged, and turn Sentinel on. The bot you just connected is
                  shared across every colony.
                </p>
              </div>
            ) : channel === "telegram" ? (
              <>
                {connected && (
                  <p className="text-[11px] text-emerald-500 flex items-center gap-1">
                    <Check className="w-3 h-3" /> A Telegram bot is already connected. Paste a
                    new token below to replace it.
                  </p>
                )}
                <button
                  type="button"
                  onClick={() => openExternal("https://t.me/BotFather")}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-semibold bg-primary/10 text-primary border border-primary/30 hover:bg-primary/20 transition-colors"
                >
                  Open @BotFather <ExternalLink className="w-3 h-3" />
                </button>
                <ol className="space-y-1.5 text-[11px] text-muted-foreground leading-relaxed list-decimal pl-4">
                  <li>
                    In the @BotFather chat, send{" "}
                    <code className="text-foreground">/newbot</code> and follow the prompts (a
                    name, then a username ending in <code className="text-foreground">bot</code>).
                  </li>
                  <li>
                    It replies with an <span className="text-foreground">HTTP API token</span> —
                    copy it and paste below.
                  </li>
                </ol>
                <div className="flex gap-2">
                  <input
                    type="password"
                    value={tgToken}
                    onChange={(e) => setTgToken(e.target.value)}
                    placeholder="123456:ABC-DEF…"
                    autoComplete="new-password"
                    className="flex-1 rounded-md border border-border/60 bg-background/60 px-2.5 py-1.5 text-xs focus:outline-none focus:border-primary/50"
                  />
                  <button
                    type="button"
                    onClick={connectTelegram}
                    disabled={busy || !tgToken.trim()}
                    className="flex items-center gap-1 px-3 py-1.5 text-xs font-semibold bg-primary text-primary-foreground hover:bg-primary/90 rounded-md disabled:opacity-50"
                  >
                    {busy && <Loader2 className="w-3 h-3 animate-spin" />}
                    Connect
                  </button>
                </div>
              </>
            ) : (
              <>
                {connected && (
                  <p className="text-[11px] text-emerald-500 flex items-center gap-1">
                    <Check className="w-3 h-3" /> A Slack app is already connected. Paste new
                    tokens below to replace it.
                  </p>
                )}
                <button
                  type="button"
                  onClick={() => openExternal("https://api.slack.com/apps")}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-semibold bg-primary/10 text-primary border border-primary/30 hover:bg-primary/20 transition-colors"
                >
                  Open Slack apps dashboard <ExternalLink className="w-3 h-3" />
                </button>
                <ol className="space-y-1.5 text-[11px] text-muted-foreground leading-relaxed list-decimal pl-4">
                  <li>
                    Click <span className="text-foreground">Create New App → From scratch</span>,
                    name it, and pick your workspace.
                  </li>
                  <li>
                    In <span className="text-foreground">Basic Information →</span>{" "}
                    <Lnk href="https://docs.slack.dev/authentication/tokens#app-level">
                      App-Level Tokens
                    </Lnk>
                    , generate a token with <code className="text-foreground">connections:write</code>{" "}
                    (<code className="text-foreground">xapp-…</code>).
                  </li>
                  <li>
                    Under{" "}
                    <Lnk href="https://api.slack.com/scopes/chat:write">OAuth &amp; Permissions</Lnk>{" "}
                    add the <code className="text-foreground">chat:write</code> bot scope.
                  </li>
                  <li>
                    Hit <span className="text-foreground">Install to Workspace</span>, copy the{" "}
                    <Lnk href="https://docs.slack.dev/authentication/tokens#bot">
                      Bot User OAuth Token
                    </Lnk>{" "}
                    (<code className="text-foreground">xoxb-…</code>), and turn on{" "}
                    <Lnk href="https://api.slack.com/apis/socket-mode">Socket Mode</Lnk>.
                  </li>
                </ol>
                <input
                  type="password"
                  value={slBotToken}
                  onChange={(e) => setSlBotToken(e.target.value)}
                  placeholder="Bot token (xoxb-…)"
                  autoComplete="new-password"
                  className="w-full rounded-md border border-border/60 bg-background/60 px-2.5 py-1.5 text-xs focus:outline-none focus:border-primary/50"
                />
                <input
                  type="password"
                  value={slAppToken}
                  onChange={(e) => setSlAppToken(e.target.value)}
                  placeholder="App-level token (xapp-…)"
                  autoComplete="new-password"
                  className="w-full rounded-md border border-border/60 bg-background/60 px-2.5 py-1.5 text-xs focus:outline-none focus:border-primary/50"
                />
                <button
                  type="button"
                  onClick={connectSlack}
                  disabled={busy || !slBotToken.trim() || !slAppToken.trim()}
                  className="flex items-center gap-1 px-3 py-1.5 text-xs font-semibold bg-primary text-primary-foreground hover:bg-primary/90 rounded-md disabled:opacity-50"
                >
                  {busy && <Loader2 className="w-3 h-3 animate-spin" />}
                  Connect
                </button>
              </>
            )}

            {error && (
              <div className="px-3 py-2 rounded-lg border border-destructive/30 bg-destructive/5 text-xs text-destructive flex items-center gap-2">
                <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                <span>{error}</span>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end px-5 py-3 border-t border-border/60">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 rounded-md transition-colors"
            >
              {doneLabel ? "Done" : "Cancel"}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
