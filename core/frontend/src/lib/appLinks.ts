/**
 * In-app deep links (`hive://…`).
 *
 * Agents can't finish every setup step — an OAuth consent screen needs a human.
 * Rather than dead-ending, a tool returns a `hive://` URL carrying what it
 * already knows, and the chat renderer turns it into an in-app navigation that
 * opens the right page with the form pre-filled. The user supplies only the
 * part the agent couldn't.
 *
 * Only `hive://` is treated as internal. Every other href stays an external
 * link — an agent must never be able to drive arbitrary in-app navigation by
 * emitting a plain path.
 *
 * Supported:
 *   hive://senders/add?provider=&from_email=&name=&from_name=&reason=
 *     → /senders?add=1&…  (opens the Add-Sender form pre-filled)
 */

/** Route path for a `hive://` link, or null when the href is not internal. */
export function parseAppLink(href: string | undefined): string | null {
  if (!href || !href.toLowerCase().startsWith("hive://")) return null;

  let url: URL;
  try {
    url = new URL(href);
  } catch {
    return null;
  }

  // URL parses hive://senders/add as host="senders", pathname="/add".
  const target = `${url.host}${url.pathname}`.replace(/\/+$/, "");
  if (target !== "senders/add") return null;

  const params = new URLSearchParams(url.search);
  params.set("add", "1");
  return `/senders?${params.toString()}`;
}
