// Curated provider/tool allowlist for the desktop UI. The runtime
// catalog is much wider (Apollo, Apify, Drive, Sheets, terminal, browser,
// charts, …) but only this curated subset is surfaced to users today —
// keeps the credentials page and tool editor focused on what we actually
// support end-to-end, and avoids overwhelming the user with credentials
// they can't usefully connect.

/** Tool ``provider`` field values that the UI exposes. The provider is
 * the short id from the runtime (``google``, ``github``, …). Used by
 * the tools editor to filter visible tool rows. */
export const VISIBLE_PROVIDERS: ReadonlySet<string> = new Set([
  "google",
  "github",
  "hubspot",
  "slack",
  "notion",
]);

/** Credential spec ids that the credentials page renders as cards.
 * A subset of {@link VISIBLE_PROVIDERS}: slack stays a visible *tool*
 * provider but is intentionally omitted here so it isn't surfaced as a
 * (not-yet-connectable) credential card. */
export const VISIBLE_CREDENTIAL_IDS: ReadonlySet<string> = new Set([
  "google",
  "github",
  "hubspot",
  "notion",
  "apollo",
]);

/** Within Google we only ship Gmail, Calendar, and Docs today — Drive
 * and Sheets exist in the runtime but aren't part of the curated set.
 * Match by tool-name prefix:
 *   - ``gmail_*``           — gmail_tool (gmail_list_messages, …)
 *   - ``calendar_*``        — calendar_tool (calendar_create_event, …)
 *   - ``google_docs_*``     — google_docs_tool (google_docs_create_document, …)
 * The Calendar prefix is ``calendar_`` rather than ``google_calendar_``
 * because the runtime names the tools without the ``google_`` namespace. */
const GOOGLE_TOOL_PREFIXES = ["gmail_", "calendar_", "google_docs_"];

/** Translate a ``credential_id`` (as known by the credentials API and
 * the OAuth handoff) to the matching ``provider`` value attached to
 * tool metadata. All curated providers now use the same string for
 * both fields, so this is a simple membership check. Returns null
 * when the credential isn't part of the curated set. */
export function credentialIdToProvider(credentialId: string): string | null {
  return VISIBLE_PROVIDERS.has(credentialId) ? credentialId : null;
}

// Re-export the auto-enable helper so callers don't need to know which
// module owns it. Implementation lives next door to keep this file
// dependency-free for the lightweight allowlist consumers.
export { autoEnableProviderAcrossQueens } from "./auto-enable-tools";

/** True when a tool should appear in the desktop UI given its provider
 * and runtime tool name. Only "hive-tools" (the OAuth-credentialed
 * MCP tools that carry a ``provider`` field) are subject to the
 * allowlist; tools without a provider — gcu-tools, chart-tools,
 * system tools, and other credential-less helpers — pass through
 * unchanged. */
export function isVisibleTool(
  provider: string | null | undefined,
  name: string,
): boolean {
  if (!provider) return true;
  if (!VISIBLE_PROVIDERS.has(provider)) return false;
  if (provider === "google") {
    return GOOGLE_TOOL_PREFIXES.some((p) => name.startsWith(p));
  }
  return true;
}
