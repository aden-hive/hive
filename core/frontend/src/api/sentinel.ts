import { api } from "./client";

/** Per-colony Sentinel (escalation) settings, mirrors notifications.json. */
export interface SentinelConfig {
  colony_id: string;
  sentinel_enabled: boolean;
  // "hive" is the built-in, always-connected default channel (Hive Inbox);
  // telegram/slack are opt-in upgrades that need a token.
  channel: "hive" | "telegram" | "slack" | null;
  target: Record<string, string>;
  allowlist: string[];
  thread: Record<string, unknown>;
  /** Per-colony idle budget in seconds; null = inherit the global default. */
  classify_after_seconds: number | null;
  credentials: SentinelCredentialStatus;
}

export interface SentinelCredentialStatus {
  telegram: { configured: boolean };
  slack: { bot: boolean; app: boolean };
}

export interface SentinelConfigUpdate {
  sentinel_enabled: boolean;
  channel: "hive" | "telegram" | "slack" | null;
  target: Record<string, string>;
  allowlist: string[];
  /** Per-colony idle budget in seconds; null clears the override. */
  classify_after_seconds: number | null;
}

export interface TelegramValidateResult {
  ok: boolean;
  bot_username?: string;
  bot_name?: string;
  error?: string;
}

export interface TelegramDetectResult {
  ok: boolean;
  pending?: boolean;
  chat_id?: string | null;
  chat_title?: string | null;
  sender_id?: string | null;
  sender_name?: string | null;
  error?: string;
}

export interface SlackValidateResult {
  ok: boolean;
  team?: string;
  bot_user?: string;
  error?: string;
}

export interface TestSendResult {
  ok: boolean;
  message_id?: string | null;
  error?: string | null;
}

export const sentinelApi = {
  /** Current per-colony config + which channel tokens are configured. */
  getConfig: (colonyName: string) =>
    api.get<SentinelConfig>(
      `/colony/${encodeURIComponent(colonyName)}/notifications`,
    ),

  /** Save the per-colony config (enable/channel/target/allowlist). */
  updateConfig: (colonyName: string, body: SentinelConfigUpdate) =>
    api.put<SentinelConfig>(
      `/colony/${encodeURIComponent(colonyName)}/notifications`,
      body,
    ),

  /** Send a test message to the configured (or supplied) destination. */
  test: (
    colonyName: string,
    override?: { channel: string; target: Record<string, string> },
  ) =>
    api.post<TestSendResult>(
      `/colony/${encodeURIComponent(colonyName)}/notifications/test`,
      override ?? {},
    ),

  /** Which messaging tokens are saved (global, not per-colony). */
  credentialStatus: () =>
    api.get<SentinelCredentialStatus>(`/sentinel/credentials`),

  /** Validate a Telegram bot token (getMe). Pass the just-typed token. */
  validateTelegram: (token: string) =>
    api.post<TelegramValidateResult>(`/sentinel/telegram/validate`, { token }),

  /** Discover the chat id after the user DMs the bot (getUpdates). */
  detectTelegramChat: () =>
    api.post<TelegramDetectResult>(`/sentinel/telegram/detect-chat`, {}),

  /** Validate a Slack bot token (auth.test). */
  validateSlack: (token: string) =>
    api.post<SlackValidateResult>(`/sentinel/slack/validate`, { token }),
};
