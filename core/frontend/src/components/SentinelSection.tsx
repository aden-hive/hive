import { useCallback, useEffect, useRef, useState } from "react";
import {
  Bell,
  Send,
  Loader2,
  Check,
  AlertCircle,
  ExternalLink,
  ChevronLeft,
  Sparkles,
  X,
} from "lucide-react";
import {
  sentinelApi,
  type SentinelConfig,
  type SentinelCredentialStatus,
} from "@/api/sentinel";
import { credentialsApi } from "@/api/credentials";
import { useGlobalEvents } from "@/hooks/use-sse";
import { useColonyWorkers } from "@/context/ColonyWorkersContext";
import { useQueensAuthorizationPrompt } from "@/context/QueensAuthorizationPromptContext";
import { getProviderLogo } from "@/data/providerLogos";
import { ProviderLogo } from "@/components/ProviderLogo";
import { Switch } from "./Switch";

type Channel = "telegram" | "slack";

const linkCls =
  "inline-flex items-center gap-0.5 text-primary hover:underline cursor-pointer";

function openExternal(url: string) {
  window.open(url, "_blank", "noopener");
}

/** Brand mark for a messaging channel (Telegram / Slack), drawn from the
 *  shared provider-logo table so it matches the credentials UI. */
function ChannelLogo({ provider, size = 18 }: { provider: string; size?: number }) {
  const logo = getProviderLogo(provider);
  if (!logo) return null;
  return <ProviderLogo provider={provider} size={size} />;
}

/** Inline external link — opens in the user's regular browser via the
 *  preload bridge (Electron won't follow a plain <a target="_blank">). */
function Lnk({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <span className={linkCls} onClick={() => openExternal(href)}>
      {children} <ExternalLink className="w-2.5 h-2.5" />
    </span>
  );
}

function destinationLabel(cfg: SentinelConfig | null): string | null {
  if (!cfg || !cfg.sentinel_enabled || !cfg.channel) return null;
  // Hive Inbox is the built-in channel: always connected, no per-colony
  // destination to show.
  if (cfg.channel === "hive") return "Hive Inbox";
  const dest =
    cfg.channel === "telegram" ? cfg.target?.chat_id : cfg.target?.channel;
  return `${cfg.channel}${dest ? ` → ${dest}` : ""}`;
}

/**
 * Automations-tab entry point for Sentinel: a compact status card with a
 * "Set up Sentinel" button that opens the configuration modal. Once saved,
 * both the per-colony setting and the (encrypted) channel token persist, so
 * it survives a restart.
 */
export function SentinelSection({ colonyName }: { colonyName: string | null }) {
  const [cfg, setCfg] = useState<SentinelConfig | null>(null);
  const [open, setOpen] = useState(false);

  // Tracks the colony this section is currently for, so a getConfig response
  // that resolves after a colony switch (or one fired by the global-event
  // listener mid-switch) is dropped instead of showing the previous colony's
  // Sentinel state under the new colony.
  const colonyNameRef = useRef(colonyName);
  colonyNameRef.current = colonyName;

  const load = useCallback(() => {
    if (!colonyName) return;
    const forColony = colonyName;
    sentinelApi
      .getConfig(forColony)
      .then((c) => {
        if (colonyNameRef.current === forColony) setCfg(c);
      })
      .catch(() => {
        if (colonyNameRef.current === forColony) setCfg(null);
      });
  }, [colonyName]);

  useEffect(() => {
    load();
  }, [load]);

  // Refetch when the queen's `sentinel_setup` tool stores tokens or writes the
  // colony's notifications config out-of-band. It emits the process-wide
  // `tool_catalog_refreshed` global event (the same signal a human credential
  // save pairs with); `getConfig` returns both the colony config and the
  // embedded token status, so one refetch keeps this card live without a
  // manual reopen.
  useGlobalEvents({
    eventTypes: ["tool_catalog_refreshed"],
    onEvent: () => load(),
  });

  if (!colonyName) return null;

  const on = !!cfg?.sentinel_enabled;
  const label = destinationLabel(cfg);

  // Matches the Cloud + Schedules sections' centered empty-state rhythm
  // (rounded-full icon badge → headline → subhead → action), so all three
  // automation sections line up. "On" mirrors the cloud deployed state's
  // emerald accent + pulsing dot.
  return (
    <div className="border-b border-border/40">
      <div className="flex flex-col items-center text-center px-2 py-10">
        {on ? (
          <div className="relative w-10 h-10 rounded-full bg-emerald-500/10 border border-emerald-500/25 flex items-center justify-center text-emerald-600 dark:text-emerald-400 mb-3">
            <Bell className="w-4 h-4" />
            <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-emerald-500 border-2 border-card animate-pulse" />
          </div>
        ) : (
          <div className="w-10 h-10 rounded-full bg-primary/10 border border-primary/20 flex items-center justify-center text-primary mb-3">
            <Bell className="w-4 h-4" />
          </div>
        )}
        <h3 className="text-sm font-semibold text-foreground mb-1.5">
          {on ? "Sentinel is watching" : "Get pinged when this colony needs you"}
        </h3>
        <p className="text-[11.5px] text-muted-foreground leading-relaxed mb-4 max-w-[260px]">
          {on && label
            ? `Pinging you on ${label} when it hits a real blocker. Reply from anywhere to keep it going.`
            : "Get pinged when this colony hits a real blocker, and reply to keep it going. Spurious “shall I continue?” pauses are auto-resumed."}
        </p>
        {on ? (
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md border border-emerald-500/20 text-[10px] font-semibold uppercase tracking-wider bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-500/15 hover:border-emerald-500/30 transition-colors"
          >
            <Bell className="w-3 h-3" />
            Manage Sentinel
          </button>
        ) : (
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-xs font-semibold bg-primary text-primary-foreground hover:bg-primary/90 transition-colors shadow-sm"
          >
            <Bell className="w-3.5 h-3.5" />
            Set up Sentinel
          </button>
        )}
      </div>

      {open && (
        <SentinelSetupModal
          colonyName={colonyName}
          onClose={() => setOpen(false)}
          onSaved={() => {
            load();
            setOpen(false);
          }}
        />
      )}
    </div>
  );
}

// ===========================================================================
// Setup modal
// ===========================================================================

function SentinelSetupModal({
  colonyName,
  onClose,
  onSaved,
}: {
  colonyName: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // "alerts" is the parent screen (channel → on/off → interval). "messaging"
  // is the drill-in child where the channel's bot/app is actually connected.
  const [view, setView] = useState<"alerts" | "messaging">("alerts");

  const [channel, setChannel] = useState<Channel>("telegram");
  const [enabled, setEnabled] = useState(false);
  const [allowlist, setAllowlist] = useState<string[]>([]);
  // Per-colony idle budget in minutes; null = inherit the global default.
  const [escalateAfterMin, setEscalateAfterMin] = useState<number | null>(null);
  const [creds, setCreds] = useState<SentinelCredentialStatus | null>(null);

  // Telegram connect state
  const [tgToken, setTgToken] = useState("");
  const [tgBusy, setTgBusy] = useState(false);
  const [tgConnectedAs, setTgConnectedAs] = useState<string | null>(null);
  const [tgChatId, setTgChatId] = useState("");
  const [tgChatLabel, setTgChatLabel] = useState<string | null>(null);
  const [tgDetectMsg, setTgDetectMsg] = useState<string | null>(null);

  // Slack connect state
  const [slBotToken, setSlBotToken] = useState("");
  const [slAppToken, setSlAppToken] = useState("");
  const [slBusy, setSlBusy] = useState(false);
  const [slConnectedTeam, setSlConnectedTeam] = useState<string | null>(null);
  const [slChannel, setSlChannel] = useState("");

  const { suppressNext } = useQueensAuthorizationPrompt();
  // Hand the whole channel setup to the colony's queen: it drives the browser
  // to create the Slack app / Telegram bot, stores the tokens, points Sentinel
  // at a channel, and turns it on (the hive.{slack,telegram}-notifications-setup
  // skills + the sentinel_setup tool). Only available when a live colony session
  // is mounted to receive the prompt (requestQueenPrompt is non-null).
  const { requestQueenPrompt } = useColonyWorkers();
  const agentSetupAvailable = !!requestQueenPrompt;
  const startAgentSetup = (which: Channel | "auto") => {
    if (!requestQueenPrompt) return;
    const prompts: Record<Channel | "auto", string> = {
      slack:
        `Help me connect Slack notifications (Sentinel) for the "${colonyName}" colony. ` +
        `Use the browser to create and configure the Slack app, install it, store the bot ` +
        `and app-level tokens, then point Sentinel at a channel and send a test so I'm ` +
        `notified on Slack when this colony needs me.`,
      telegram:
        `Help me connect Telegram notifications (Sentinel) for the "${colonyName}" colony. ` +
        `Use the browser to create a Telegram bot via @BotFather, store its token, detect my ` +
        `chat, point Sentinel at it, and send a test so I'm notified on Telegram when this ` +
        `colony needs me.`,
      auto:
        `Help me set up notifications (Sentinel) for the "${colonyName}" colony so I get pinged ` +
        `when it needs me. Set it up end to end in the browser; if it isn't already clear from ` +
        `what's connected, ask me whether I want Slack or Telegram first.`,
    };
    requestQueenPrompt(prompts[which]);
    onClose();
  };

  const [saving, setSaving] = useState(false);
  const [testState, setTestState] = useState<
    { kind: "idle" | "ok" } | { kind: "err"; msg: string } | { kind: "busy" }
  >({ kind: "idle" });

  const telegramConfigured = !!creds?.telegram.configured;
  const slackConfigured = !!(creds?.slack.bot && creds?.slack.app);

  useEffect(() => {
    setLoading(true);
    sentinelApi
      .getConfig(colonyName)
      .then((c) => {
        setCreds(c.credentials);
        setEnabled(c.sentinel_enabled);
        setChannel((c.channel as Channel) ?? "telegram");
        setAllowlist(c.allowlist ?? []);
        setEscalateAfterMin(
          c.classify_after_seconds != null
            ? Math.round(c.classify_after_seconds / 60)
            : null,
        );
        setTgChatId(c.channel === "telegram" ? (c.target?.chat_id ?? "") : "");
        setSlChannel(c.channel === "slack" ? (c.target?.channel ?? "") : "");
      })
      .catch((e) => setError(e?.message ?? "Failed to load Sentinel config"))
      .finally(() => setLoading(false));
  }, [colonyName]);

  const refreshCreds = useCallback(async () => {
    try {
      setCreds(await sentinelApi.credentialStatus());
    } catch {
      /* non-fatal */
    }
  }, []);

  const connectTelegram = async () => {
    if (!tgToken.trim()) return;
    setTgBusy(true);
    setError(null);
    try {
      await credentialsApi.save("telegram", { bot_token: tgToken.trim() });
      const v = await sentinelApi.validateTelegram(tgToken.trim());
      if (!v.ok) {
        setError(v.error ?? "Invalid bot token");
        return;
      }
      setTgConnectedAs(v.bot_username ? `@${v.bot_username}` : (v.bot_name ?? "bot"));
      setTgToken("");
      await refreshCreds();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setTgBusy(false);
    }
  };

  const detectTelegramChat = async () => {
    setTgBusy(true);
    setTgDetectMsg(null);
    setError(null);
    try {
      const r = await sentinelApi.detectTelegramChat();
      if (!r.ok) {
        setTgDetectMsg(r.error ?? "No message detected yet.");
        return;
      }
      if (r.chat_id) setTgChatId(r.chat_id);
      setTgChatLabel(r.chat_title ?? null);
      if (r.sender_id) {
        setAllowlist((prev) =>
          prev.includes(r.sender_id as string) ? prev : [...prev, r.sender_id as string],
        );
      }
      setTgDetectMsg(`Found ${r.chat_title ?? r.chat_id}.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setTgBusy(false);
    }
  };

  const connectSlack = async () => {
    if (!slBotToken.trim() || !slAppToken.trim()) return;
    setSlBusy(true);
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
      setSlConnectedTeam(v.team ?? "workspace");
      setSlBotToken("");
      setSlAppToken("");
      await refreshCreds();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSlBusy(false);
    }
  };

  const target: Record<string, string> =
    channel === "telegram"
      ? { chat_id: tgChatId.trim() }
      : { channel: slChannel.trim() };

  const canEnable =
    channel === "telegram"
      ? telegramConfigured && !!tgChatId.trim()
      : slackConfigured && !!slChannel.trim();

  // Destination shown on the connected channel row (chat title/id or #channel).
  const destinationText =
    channel === "telegram" ? tgChatLabel || tgChatId : slChannel;

  // Set when "Done" is pressed with the channel half-configured, so the
  // connect sub-forms can flag their empty required fields (classic on-submit
  // validation). Reset whenever we (re-)enter the messaging child.
  const [triedDone, setTriedDone] = useState(false);
  const openMessaging = (ch?: Channel) => {
    if (ch) setChannel(ch);
    setTriedDone(false);
    setView("messaging");
  };
  const doneMessaging = () => {
    if (canEnable) {
      setTriedDone(false);
      setView("alerts");
    } else {
      setTriedDone(true);
    }
  };

  // "Delete" the channel for this colony: clear the per-colony destination and
  // switch off, so the chooser reappears. Shared bot/app creds are untouched —
  // other colonies keep using them.
  const removeChannel = () => {
    if (channel === "telegram") {
      setTgChatId("");
      setTgChatLabel(null);
    } else {
      setSlChannel("");
    }
    setEnabled(false);
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await sentinelApi.updateConfig(colonyName, {
        sentinel_enabled: enabled && canEnable,
        channel,
        target,
        allowlist,
        classify_after_seconds:
          escalateAfterMin != null ? escalateAfterMin * 60 : null,
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setSaving(false);
    }
  };

  const sendTest = async () => {
    setTestState({ kind: "busy" });
    try {
      const r = await sentinelApi.test(colonyName, { channel, target });
      setTestState(r.ok ? { kind: "ok" } : { kind: "err", msg: r.error ?? "Failed" });
    } catch (e) {
      setTestState({ kind: "err", msg: e instanceof Error ? e.message : String(e) });
    }
  };

  return (
    <>
      <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
        <div className="bg-card border border-border rounded-xl shadow-2xl w-full max-w-md max-h-[88vh] flex flex-col pointer-events-auto">
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-border/60">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center">
                <Bell className="w-4 h-4 text-primary" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-foreground">Set up Sentinel</h2>
              </div>
            </div>
            <button
              onClick={onClose}
              className="p-1.5 rounded-md hover:bg-muted/60 text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Body */}
          <div className="px-5 py-4 overflow-y-auto">
            {loading ? (
              <div className="flex justify-center py-10">
                <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <>
                {view === "messaging" ? (
                  <>
                    <button
                      type="button"
                      onClick={() => setView("alerts")}
                      className="flex items-center gap-1 text-[11px] font-medium text-muted-foreground hover:text-foreground mb-3"
                    >
                      <ChevronLeft className="w-3.5 h-3.5" /> Back to alerts
                    </button>
                    <div className="flex items-center gap-2 mb-3">
                      <ChannelLogo provider={channel} size={18} />
                      <span className="text-sm font-semibold text-foreground capitalize">
                        {channel}
                      </span>
                    </div>

                    {channel === "telegram" ? (
                      <TelegramConnect
                        configured={telegramConfigured}
                        connectedAs={tgConnectedAs}
                        token={tgToken}
                        setToken={setTgToken}
                        busy={tgBusy}
                        onConnect={connectTelegram}
                        chatId={tgChatId}
                        setChatId={setTgChatId}
                        chatLabel={tgChatLabel}
                        detectMsg={tgDetectMsg}
                        onDetect={detectTelegramChat}
                        showRequired={triedDone}
                        onAgentSetup={
                          agentSetupAvailable ? () => startAgentSetup("telegram") : null
                        }
                      />
                    ) : (
                      <SlackConnect
                        configured={slackConfigured}
                        connectedTeam={slConnectedTeam}
                        botToken={slBotToken}
                        setBotToken={setSlBotToken}
                        appToken={slAppToken}
                        setAppToken={setSlAppToken}
                        busy={slBusy}
                        onConnect={connectSlack}
                        channelId={slChannel}
                        setChannelId={setSlChannel}
                        showRequired={triedDone}
                        onAgentSetup={
                          agentSetupAvailable ? () => startAgentSetup("slack") : null
                        }
                      />
                    )}

                    {/* Allowlist */}
                    <div className="mt-4">
                      <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5 block">
                        Allowed repliers
                      </label>
                      <input
                        type="text"
                        value={allowlist.join(", ")}
                        onChange={(e) =>
                          setAllowlist(
                            e.target.value
                              .split(/[\s,]+/)
                              .map((s) => s.trim())
                              .filter(Boolean),
                          )
                        }
                        placeholder={
                          channel === "telegram" ? "Telegram user IDs" : "Slack user IDs"
                        }
                        className="w-full rounded-md border border-border/60 bg-background/60 px-2.5 py-1.5 text-xs focus:outline-none focus:border-primary/50"
                      />
                      <p className="text-[10px] text-muted-foreground mt-1">
                        Only these senders can drive the colony. Auto-filled when you
                        detect your Telegram chat.
                      </p>
                    </div>
                  </>
                ) : (
                  <>
                    {/* 1 — Channel (the prerequisite) */}
                    <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5 block">
                      Channel
                    </label>
                    {canEnable ? (
                      <div className="flex items-center justify-between gap-2 rounded-lg border border-border/50 bg-muted/20 p-3">
                        <div className="flex items-center gap-2 min-w-0">
                          <ChannelLogo provider={channel} size={18} />
                          <span className="text-xs font-medium text-foreground capitalize flex-shrink-0">
                            {channel}
                          </span>
                          <Check className="w-3.5 h-3.5 text-emerald-500 flex-shrink-0" />
                          {destinationText && (
                            <span className="text-[11px] text-muted-foreground truncate">
                              → {destinationText}
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-1 flex-shrink-0">
                          <button
                            type="button"
                            onClick={() => openMessaging()}
                            className="px-2 py-1 text-[11px] font-medium text-primary hover:bg-primary/10 rounded-md"
                          >
                            Edit
                          </button>
                          <button
                            type="button"
                            onClick={removeChannel}
                            className="px-2 py-1 text-[11px] font-medium text-destructive hover:bg-destructive/10 rounded-md"
                          >
                            Delete
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="grid grid-cols-2 gap-2">
                        {(["telegram", "slack"] as Channel[]).map((ch) => {
                          const credsReady =
                            ch === "telegram" ? telegramConfigured : slackConfigured;
                          return (
                            <button
                              key={ch}
                              type="button"
                              onClick={() => openMessaging(ch)}
                              className="flex flex-col items-center justify-center gap-1.5 py-4 rounded-lg border border-border/50 bg-muted/20 hover:bg-muted/40 hover:border-primary/40 transition-colors"
                            >
                              <ChannelLogo provider={ch} size={22} />
                              <span className="text-xs font-medium text-foreground capitalize">
                                {ch}
                              </span>
                              {credsReady ? (
                                <span className="text-[10px] text-emerald-500 flex items-center gap-0.5">
                                  <Check className="w-2.5 h-2.5" /> Connected
                                </span>
                              ) : (
                                <span className="text-[10px] text-muted-foreground">
                                  Set up
                                </span>
                              )}
                            </button>
                          );
                        })}
                      </div>
                    )}

                    {/* Agent auto-setup — top-level entry so it's findable
                        without drilling into a channel form. Shown while
                        Sentinel isn't on yet and a live colony session exists
                        to receive the prompt. The agent handles either channel
                        (create/reuse the Slack app or Telegram bot, tokens,
                        channel, enable); it asks which if unclear. */}
                    {agentSetupAvailable && !enabled && (
                      <button
                        type="button"
                        onClick={() => startAgentSetup("auto")}
                        className="mt-3 w-full flex items-start gap-2.5 p-3 rounded-lg border border-primary/30 bg-primary/5 hover:bg-primary/10 hover:border-primary/40 text-left transition-colors"
                      >
                        <Sparkles className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
                        <span className="min-w-0">
                          <span className="block text-[11px] font-semibold text-foreground">
                            Set this up with the agent
                          </span>
                          <span className="block text-[10.5px] text-muted-foreground leading-relaxed mt-0.5">
                            Your colony's agent drives the browser to set up Slack or
                            Telegram — creating the app/bot, storing tokens, picking
                            the channel, and turning Sentinel on for you.
                          </span>
                        </span>
                      </button>
                    )}

                    {/* 2 — Turn on (locked until a channel is set up) */}
                    <div className="mt-5 flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <p
                          className={`text-xs font-medium ${
                            canEnable ? "text-foreground" : "text-muted-foreground"
                          }`}
                        >
                          Turn on Sentinel
                        </p>
                        <p className="text-[10px] text-muted-foreground mt-0.5">
                          {canEnable
                            ? "Watch this colony and ping you when it stalls."
                            : "Set up a channel above first."}
                        </p>
                      </div>
                      <Switch
                        checked={enabled && canEnable}
                        disabled={!canEnable}
                        onChange={setEnabled}
                      />
                    </div>

                    {/* 3 — Interval (locked until on) */}
                    <div
                      className={`mt-5 ${
                        canEnable && enabled ? "" : "opacity-50"
                      }`}
                    >
                      <label className="text-[11px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5 block">
                        Alert me if stuck for
                      </label>
                      <select
                        value={escalateAfterMin ?? ""}
                        disabled={!canEnable || !enabled}
                        onChange={(e) =>
                          setEscalateAfterMin(
                            e.target.value === "" ? null : Number(e.target.value),
                          )
                        }
                        className="w-full rounded-md border border-border/60 bg-background/60 px-2.5 py-1.5 text-xs focus:outline-none focus:border-primary/50 disabled:cursor-not-allowed"
                      >
                        <option value="">15 minutes (default)</option>
                        <option value={1}>1 minute</option>
                        <option value={5}>5 minutes</option>
                        <option value={30}>30 minutes</option>
                        <option value={60}>1 hour</option>
                      </select>
                    </div>
                  </>
                )}

                {error && (
                  <div className="mt-4 px-3 py-2 rounded-lg border border-destructive/30 bg-destructive/5 text-xs text-destructive flex items-center gap-2">
                    <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
                    <span>{error}</span>
                  </div>
                )}
              </>
            )}
          </div>

          {/* Footer */}
          {!loading &&
            (view === "messaging" ? (
              // Child view: return to Alerts. "Done" stays clickable and
              // validates on click — empty required fields flag themselves
              // (classic on-submit validation). Credentials are already saved
              // on Connect; the destination lives in state.
              <div className="flex items-center justify-end px-5 py-3 border-t border-border/60">
                <button
                  type="button"
                  onClick={doneMessaging}
                  className="flex items-center gap-1.5 px-4 py-1.5 text-xs font-semibold bg-primary text-primary-foreground hover:bg-primary/90 rounded-md transition-colors"
                >
                  Done
                </button>
              </div>
            ) : (
              <div className="flex items-center justify-between gap-2 px-5 py-3 border-t border-border/60">
                <div className="flex items-center gap-2 min-w-0">
                  {canEnable && (
                    <button
                      type="button"
                      onClick={sendTest}
                      disabled={testState.kind === "busy"}
                      className="flex items-center gap-1 px-2 py-1 text-[11px] font-medium text-primary hover:bg-primary/10 rounded-md disabled:opacity-50"
                    >
                      {testState.kind === "busy" ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : (
                        <Send className="w-3 h-3" />
                      )}
                      Send test
                      {testState.kind === "ok" && (
                        <span className="text-emerald-500">✓</span>
                      )}
                    </button>
                  )}
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <button
                    type="button"
                    onClick={onClose}
                    className="px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 rounded-md transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={save}
                    disabled={saving}
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-primary text-primary-foreground hover:bg-primary/90 rounded-md transition-colors disabled:opacity-50"
                  >
                    {saving && <Loader2 className="w-3 h-3 animate-spin" />}
                    {saving ? "Saving…" : "Save"}
                  </button>
                </div>
              </div>
            ))}
          {testState.kind === "err" && (
            <div className="px-5 pb-3 -mt-1 text-[11px] text-destructive">
              {testState.msg}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Telegram connect sub-form
// ---------------------------------------------------------------------------

function TelegramConnect(props: {
  configured: boolean;
  connectedAs: string | null;
  token: string;
  setToken: (s: string) => void;
  busy: boolean;
  onConnect: () => void;
  chatId: string;
  setChatId: (s: string) => void;
  chatLabel: string | null;
  detectMsg: string | null;
  onDetect: () => void;
  showRequired?: boolean;
  /** Hand the whole flow to the colony's queen (browser-driven BotFather
   *  bot creation + token store + chat detection). Null when no live colony
   *  session is mounted to receive the prompt — the manual steps are the
   *  fallback. */
  onAgentSetup?: (() => void) | null;
}) {
  const connected = props.configured || !!props.connectedAs;
  const [reconfig, setReconfig] = useState(false);
  const showForm = !connected || reconfig;
  return (
    <div className="space-y-3">
      {props.onAgentSetup && (
        <button
          type="button"
          onClick={props.onAgentSetup}
          className="w-full flex items-start gap-2.5 p-3 rounded-lg border border-primary/30 bg-primary/5 hover:bg-primary/10 hover:border-primary/40 text-left transition-colors"
        >
          <Sparkles className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
          <span className="min-w-0">
            <span className="block text-[11px] font-semibold text-foreground">
              Set this up with the agent
            </span>
            <span className="block text-[10.5px] text-muted-foreground leading-relaxed mt-0.5">
              Your colony's agent drives the browser to create the Telegram bot via
              @BotFather, store its token, and detect your chat. Or do it manually
              below.
            </span>
          </span>
        </button>
      )}
      <Step n={1} title="Connect a bot" done={connected} required>
        {!showForm ? (
          <p className="text-[11px] text-emerald-500 flex items-center gap-1">
            <Check className="w-3 h-3" /> Bot connected
            {props.connectedAs ? ` (${props.connectedAs})` : ""}.
            <button
              type="button"
              onClick={() => setReconfig(true)}
              className="ml-1 text-muted-foreground hover:text-foreground underline"
            >
              Reconnect
            </button>
          </p>
        ) : (
          <>
            <button
              type="button"
              onClick={() => openExternal("https://t.me/BotFather")}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-semibold bg-primary/10 text-primary border border-primary/30 hover:bg-primary/20 transition-colors"
            >
              Open @BotFather <ExternalLink className="w-3 h-3" />
            </button>
            <ol className="mt-2.5 space-y-1.5 text-[11px] text-muted-foreground leading-relaxed list-decimal pl-4">
              <li>
                In the @BotFather chat, send{" "}
                <code className="text-foreground">/newbot</code> and follow the
                prompts (pick a name, then a username ending in{" "}
                <code className="text-foreground">bot</code>).
              </li>
              <li>
                It replies with an{" "}
                <span className="text-foreground">HTTP API token</span> — copy it
                and paste below.
              </li>
            </ol>
            <p className="mt-2 text-[10.5px] text-muted-foreground">
              New to Telegram bots?{" "}
              <Lnk href="https://core.telegram.org/bots/features#botfather">
                Telegram's bot guide
              </Lnk>
              .
            </p>
            <div className="flex gap-2 mt-2">
              <input
                type="password"
                value={props.token}
                onChange={(e) => props.setToken(e.target.value)}
                placeholder="123456:ABC-DEF…"
                className="flex-1 rounded-md border border-border/60 bg-background/60 px-2.5 py-1.5 text-xs focus:outline-none focus:border-primary/50"
              />
              <button
                type="button"
                onClick={props.onConnect}
                disabled={props.busy || !props.token.trim()}
                className="flex items-center gap-1 px-3 py-1.5 text-xs font-semibold bg-primary text-primary-foreground hover:bg-primary/90 rounded-md disabled:opacity-50"
              >
                {props.busy && <Loader2 className="w-3 h-3 animate-spin" />}
                Connect
              </button>
            </div>
            {props.showRequired && !connected && (
              <p className="text-[11px] text-destructive mt-1">
                Connect your bot to continue.
              </p>
            )}
          </>
        )}
      </Step>

      <Step n={2} title="Pick where to ping you" done={!!props.chatId} required>
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Open your bot in Telegram and send it any message, then click Detect —
          we'll fill in your chat automatically.
        </p>
        <div className="flex gap-2 mt-2">
          <input
            type="text"
            value={props.chatId}
            onChange={(e) => props.setChatId(e.target.value)}
            placeholder="chat id"
            className={`flex-1 rounded-md border bg-background/60 px-2.5 py-1.5 text-xs focus:outline-none focus:border-primary/50 ${
              props.showRequired && !props.chatId.trim()
                ? "border-destructive"
                : "border-border/60"
            }`}
          />
          <button
            type="button"
            onClick={props.onDetect}
            disabled={props.busy || !props.configured}
            className="px-3 py-1.5 text-xs font-medium bg-primary/10 text-primary hover:bg-primary/20 border border-primary/30 rounded-md disabled:opacity-50"
          >
            Detect
          </button>
        </div>
        {props.showRequired && !props.chatId.trim() ? (
          <p className="text-[11px] text-destructive mt-1">This field is required.</p>
        ) : props.chatLabel ? (
          <p className="text-[11px] text-emerald-500 mt-1">{props.chatLabel}</p>
        ) : props.detectMsg ? (
          <p className="text-[11px] text-muted-foreground mt-1">{props.detectMsg}</p>
        ) : null}
      </Step>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Slack connect sub-form
// ---------------------------------------------------------------------------

function SlackConnect(props: {
  configured: boolean;
  connectedTeam: string | null;
  botToken: string;
  setBotToken: (s: string) => void;
  appToken: string;
  setAppToken: (s: string) => void;
  busy: boolean;
  onConnect: () => void;
  channelId: string;
  setChannelId: (s: string) => void;
  showRequired?: boolean;
  /** Hand the whole flow to the colony's queen (browser-driven app
   *  creation + secure token forms). Null when no live colony session is
   *  mounted to receive the prompt — the manual steps are the fallback. */
  onAgentSetup?: (() => void) | null;
}) {
  const connected = props.configured || !!props.connectedTeam;
  const [reconfig, setReconfig] = useState(false);
  const showForm = !connected || reconfig;
  return (
    <div className="space-y-3">
      {props.onAgentSetup && (
        <button
          type="button"
          onClick={props.onAgentSetup}
          className="w-full flex items-start gap-2.5 p-3 rounded-lg border border-primary/30 bg-primary/5 hover:bg-primary/10 hover:border-primary/40 text-left transition-colors"
        >
          <Sparkles className="w-4 h-4 text-primary flex-shrink-0 mt-0.5" />
          <span className="min-w-0">
            <span className="block text-[11px] font-semibold text-foreground">
              Set this up with the agent
            </span>
            <span className="block text-[10.5px] text-muted-foreground leading-relaxed mt-0.5">
              Your colony's agent drives the browser to create the Slack app,
              store its tokens, and point Sentinel at a channel for you. Or do it
              manually below.
            </span>
          </span>
        </button>
      )}
      <Step n={1} title="Connect a Slack app" done={connected} required>
        {!showForm ? (
          <p className="text-[11px] text-emerald-500 flex items-center gap-1">
            <Check className="w-3 h-3" /> Connected
            {props.connectedTeam ? ` to ${props.connectedTeam}` : ""}.
            <button
              type="button"
              onClick={() => setReconfig(true)}
              className="ml-1 text-muted-foreground hover:text-foreground underline"
            >
              Reconnect
            </button>
          </p>
        ) : (
          <>
            <button
              type="button"
              onClick={() => openExternal("https://api.slack.com/apps")}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[11px] font-semibold bg-primary/10 text-primary border border-primary/30 hover:bg-primary/20 transition-colors"
            >
              Open Slack apps dashboard <ExternalLink className="w-3 h-3" />
            </button>
            <ol className="mt-2.5 space-y-1.5 text-[11px] text-muted-foreground leading-relaxed list-decimal pl-4">
              <li>
                Click <span className="text-foreground">Create New App → From scratch</span>,
                name it, and pick your workspace.
              </li>
              <li>
                In <span className="text-foreground">Basic Information →</span>{" "}
                <Lnk href="https://docs.slack.dev/authentication/tokens#app-level">
                  App-Level Tokens
                </Lnk>
                , generate a token with{" "}
                <code className="text-foreground">connections:write</code> and copy it (
                <code className="text-foreground">xapp-…</code>).
              </li>
              <li>
                Open{" "}
                <Lnk href="https://api.slack.com/scopes/chat:write">
                  OAuth &amp; Permissions
                </Lnk>{" "}
                → under <span className="text-foreground">Bot Token Scopes</span> add{" "}
                <code className="text-foreground">chat:write</code>.
              </li>
              <li>
                Hit <span className="text-foreground">Install to Workspace</span>, then copy the{" "}
                <Lnk href="https://docs.slack.dev/authentication/tokens#bot">
                  Bot User OAuth Token
                </Lnk>{" "}
                (<code className="text-foreground">xoxb-…</code>) — paste it below.
              </li>
              <li>
                Turn on{" "}
                <Lnk href="https://api.slack.com/apis/socket-mode">Socket Mode</Lnk>.
              </li>
            </ol>
            <p className="mt-2 text-[10.5px] text-muted-foreground">
              Prefer a full walkthrough?{" "}
              <Lnk href="https://api.slack.com/quickstart">Slack's quickstart guide</Lnk>.
            </p>
            <input
              type="password"
              value={props.botToken}
              onChange={(e) => props.setBotToken(e.target.value)}
              placeholder="Bot token (xoxb-…)"
              className="w-full mt-2 rounded-md border border-border/60 bg-background/60 px-2.5 py-1.5 text-xs focus:outline-none focus:border-primary/50"
            />
            <input
              type="password"
              value={props.appToken}
              onChange={(e) => props.setAppToken(e.target.value)}
              placeholder="App-level token (xapp-…)"
              className="w-full mt-2 rounded-md border border-border/60 bg-background/60 px-2.5 py-1.5 text-xs focus:outline-none focus:border-primary/50"
            />
            <button
              type="button"
              onClick={props.onConnect}
              disabled={props.busy || !props.botToken.trim() || !props.appToken.trim()}
              className="flex items-center gap-1 mt-2 px-3 py-1.5 text-xs font-semibold bg-primary text-primary-foreground hover:bg-primary/90 rounded-md disabled:opacity-50"
            >
              {props.busy && <Loader2 className="w-3 h-3 animate-spin" />}
              Connect
            </button>
            {props.showRequired && !connected && (
              <p className="text-[11px] text-destructive mt-1">
                Connect your Slack app to continue.
              </p>
            )}
          </>
        )}
      </Step>

      <Step n={2} title="Pick a channel" done={!!props.channelId} required>
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          Invite the bot to a channel, then paste its channel ID (in Slack:
          channel name → right-click → Copy link; the ID is the last path
          segment, e.g. <code className="text-foreground">C0123ABC</code>).
        </p>
        <input
          type="text"
          value={props.channelId}
          onChange={(e) => props.setChannelId(e.target.value)}
          placeholder="C0123ABC456"
          className={`w-full mt-2 rounded-md border bg-background/60 px-2.5 py-1.5 text-xs focus:outline-none focus:border-primary/50 ${
            props.showRequired && !props.channelId.trim()
              ? "border-destructive"
              : "border-border/60"
          }`}
        />
        {props.showRequired && !props.channelId.trim() && (
          <p className="text-[11px] text-destructive mt-1">This field is required.</p>
        )}
      </Step>
    </div>
  );
}

function Step({
  n,
  title,
  done,
  required,
  children,
}: {
  n: number;
  title: string;
  done?: boolean;
  /** Show a red required asterisk while this step isn't satisfied yet. */
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border/40 bg-muted/20 p-3">
      <div className="flex items-center gap-2 mb-1.5">
        <span
          className={`w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-bold ${
            done
              ? "bg-emerald-500/20 text-emerald-500"
              : "bg-primary/15 text-primary"
          }`}
        >
          {done ? <Check className="w-2.5 h-2.5" /> : n}
        </span>
        <span className="text-[11px] font-semibold text-foreground">
          {title}
          {required && !done && (
            <span className="text-destructive ml-0.5" aria-label="required">
              *
            </span>
          )}
        </span>
      </div>
      {children}
    </div>
  );
}
