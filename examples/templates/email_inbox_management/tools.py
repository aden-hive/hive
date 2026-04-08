"""Custom script tools for Inbox Management Agent.

Provides bulk_fetch_emails — a synchronous Gmail inbox fetcher that writes
compact JSONL to the session data_dir.  Called by the fetch-emails event_loop
node as a tool (replacing the old function node approach).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

from framework.llm.provider import Tool, ToolResult, ToolUse
from framework.loader.tool_registry import _execution_context

logger = logging.getLogger(__name__)

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"
BATCH_SIZE = 50  # Metadata fetches per logging checkpoint


# ---------------------------------------------------------------------------
# Tool definitions (auto-discovered by ToolRegistry.discover_from_module)
# ---------------------------------------------------------------------------

TOOLS = {
    "bulk_fetch_emails": Tool(
        name="bulk_fetch_emails",
        description=(
            "Fetch emails from Gmail and write them to a JSONL file. "
            "Returns {filename, count, next_page_token}. Pass next_page_token "
            "from a previous call to fetch the next page. "
            "Supports Gmail search query syntax via the 'query' parameter."
        ),
        parameters={
            "type": "object",
            "properties": {
                "max_emails": {
                    "type": "string",
                    "description": "Maximum number of emails to fetch in this page (default '100')",
                },
                "page_token": {
                    "type": "string",
                    "description": (
                        "Gmail API page token from a previous call's next_page_token. "
                        "Omit for the first page."
                    ),
                },
                "after_timestamp": {
                    "type": "string",
                    "description": (
                        "Unix epoch seconds. Only fetch emails received after this time. "
                        "Used by timer cycles to skip already-processed emails."
                    ),
                },
                "account": {
                    "type": "string",
                    "description": (
                        "Account alias to use (e.g. 'timothy-home'). "
                        "Required when multiple Google accounts are connected."
                    ),
                },
                "query": {
                    "type": "string",
                    "description": (
                        "Gmail search query. Defaults to 'label:INBOX'. Supports full Gmail "
                        "search syntax: from:, to:, subject:, is:unread, is:starred, "
                        "has:attachment, label:, newer_than:, older_than:, category:, "
                        "filename:, and boolean operators (AND, OR, NOT, -, {}). "
                        "Examples: 'from:boss@example.com', 'subject:invoice is:unread', "
                        "'label:INBOX -from:noreply'. The after_timestamp parameter is "
                        "appended automatically if provided."
                    ),
                },
            },
            "required": [],
        },
    ),
    "get_current_timestamp": Tool(
        name="get_current_timestamp",
        description="Return the current Unix epoch timestamp in seconds.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_data_dir() -> str:
    """Get the session-scoped data_dir from ToolRegistry execution context."""
    ctx = _execution_context.get()
    if not ctx or "data_dir" not in ctx:
        raise RuntimeError(
            "data_dir not set in execution context. Is the tool running inside a Orchestrator?"
        )
    return ctx["data_dir"]


def _get_access_token(account: str = "") -> str:
    """Get Google OAuth access token from credential store.

    Args:
        account: Account alias (e.g. 'timothy-home'). When provided,
                 resolves the token for that specific account.
    """
    import os

    # Try credential store first (same pattern as gmail_tool.py)
    try:
        from aden_tools.credentials import CredentialStoreAdapter

        credentials = CredentialStoreAdapter.default()
        if account:
            # Strip provider prefix if LLM passes "google/alias" format
            clean_account = account.removeprefix("google/")
            token = credentials.get_by_alias("google", clean_account)
        else:
            token = credentials.get("google")
        if token:
            return token
    except Exception:
        pass

    # Fallback to environment variable
    token = os.getenv("GOOGLE_ACCESS_TOKEN")
    if token:
        return token

    raise RuntimeError(
        "Gmail credentials not configured. "
        "Connect Gmail via hive.adenhq.com or set GOOGLE_ACCESS_TOKEN."
    )


def _parse_headers(headers: list[dict]) -> dict[str, str]:
    """Extract common headers into a flat dict."""
    result: dict[str, str] = {}
    for h in headers:
        name = h.get("name", "").lower()
        if name in ("subject", "from", "to", "date", "cc"):
            result[name] = h.get("value", "")
    return result


# ---------------------------------------------------------------------------
# Core implementation (synchronous)
# ---------------------------------------------------------------------------


def _bulk_fetch_emails(
    max_emails: str = "100",
    page_token: str = "",
    after_timestamp: str = "",
    account: str = "",
    query: str = "",
) -> dict:
    """Fetch emails from Gmail and write them to emails.jsonl.

    Uses synchronous httpx.Client since this runs as a tool call inside
    an already-running async event loop.

    Args:
        max_emails: Maximum number of emails to fetch in this page.
        page_token: Gmail API page token for pagination. Omit for the first page.
        after_timestamp: Unix epoch seconds — only fetch emails after this time.
        account: Account alias (e.g. 'timothy-home') for multi-account routing.
        query: Gmail search query. Defaults to 'label:INBOX'. Supports full
               Gmail search syntax (from:, subject:, is:, label:, etc.).

    Returns:
        Dict with {filename, count, next_page_token}.
    """
    max_count = int(max_emails) if max_emails else 100
    access_token = _get_access_token(account)
    data_dir = _get_data_dir()
    Path(data_dir).mkdir(parents=True, exist_ok=True)

    http_headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    # Build Gmail query
    gmail_query = query.strip() if query and query.strip() else "label:INBOX"
    if after_timestamp and after_timestamp.strip():
        gmail_query += f" after:{after_timestamp.strip()}"

    message_ids: list[str] = []
    current_page_token: str | None = page_token if page_token else None
    next_page_token: str | None = None

    with httpx.Client(headers=http_headers, timeout=30.0) as client:
        # Phase 1: Collect message IDs (paginated, sequential)
        while len(message_ids) < max_count:
            remaining = max_count - len(message_ids)
            page_size = min(remaining, 500)

            params: dict[str, str | int] = {
                "q": gmail_query,
                "maxResults": page_size,
            }
            if current_page_token:
                params["pageToken"] = current_page_token

            resp = client.get(f"{GMAIL_API_BASE}/messages", params=params)
            if resp.status_code != 200:
                raise RuntimeError(f"Gmail list failed (HTTP {resp.status_code}): {resp.text}")

            data = resp.json()
            messages = data.get("messages", [])
            if not messages:
                break

            for msg in messages:
                if len(message_ids) >= max_count:
                    break
                message_ids.append(msg["id"])

            current_page_token = data.get("nextPageToken")
            if not current_page_token:
                break

        # Expose the Gmail API's nextPageToken so the graph can loop
        next_page_token = current_page_token

        if not message_ids:
            (Path(data_dir) / "emails.jsonl").write_text("", encoding="utf-8")
            logger.info("No inbox emails found.")
            return {
                "filename": "emails.jsonl",
                "count": 0,
                "next_page_token": None,
            }

        logger.info(f"Found {len(message_ids)} message IDs. Fetching metadata...")

        # Phase 2: Fetch metadata (sequential with retry on 429)
        emails: list[dict] = []

        for msg_id in message_ids:
            retries = 2
            for attempt in range(1 + retries):
                try:
                    r = client.get(
                        f"{GMAIL_API_BASE}/messages/{msg_id}",
                        params={"format": "metadata"},
                    )
                    if r.status_code == 200:
                        raw = r.json()
                        parsed = _parse_headers(raw.get("payload", {}).get("headers", []))
                        emails.append(
                            {
                                "id": raw.get("id"),
                                "subject": parsed.get("subject", ""),
                                "from": parsed.get("from", ""),
                                "to": parsed.get("to", ""),
                                "date": parsed.get("date", ""),
                                "snippet": raw.get("snippet", ""),
                                "labels": raw.get("labelIds", []),
                            }
                        )
                        break
                    if r.status_code == 429 and attempt < retries:
                        time.sleep(1 * (attempt + 1))
                        continue
                    logger.warning(f"Failed to fetch {msg_id}: HTTP {r.status_code}")
                    break
                except httpx.HTTPError as e:
                    if attempt < retries:
                        time.sleep(0.5)
                        continue
                    logger.warning(f"Failed to fetch {msg_id} after {retries + 1} attempts: {e}")

    dropped = len(message_ids) - len(emails)
    if dropped > 0:
        logger.warning(
            f"Dropped {dropped}/{len(message_ids)} emails during metadata fetch "
            f"(wrote {len(emails)} to emails.jsonl)"
        )

    # Phase 3: Append JSONL (append so pagination accumulates across pages)
    output_path = Path(data_dir) / "emails.jsonl"
    with open(output_path, "a", encoding="utf-8") as f:
        for email in emails:
            f.write(json.dumps(email, ensure_ascii=False) + "\n")

    logger.info(f"Wrote {len(emails)} emails to emails.jsonl ({output_path.stat().st_size} bytes)")
    return {
        "filename": "emails.jsonl",
        "count": len(emails),
        "next_page_token": next_page_token,
    }


# ---------------------------------------------------------------------------
# Unified tool executor (auto-discovered by ToolRegistry.discover_from_module)
# ---------------------------------------------------------------------------


def _get_current_timestamp() -> dict:
    """Return current Unix epoch timestamp."""
    return {"timestamp": str(int(time.time()))}


def tool_executor(tool_use: ToolUse) -> ToolResult:
    """Dispatch tool calls to their implementations."""
    if tool_use.name == "bulk_fetch_emails":
        try:
            result = _bulk_fetch_emails(
                max_emails=tool_use.input.get("max_emails", "100"),
                page_token=tool_use.input.get("page_token", ""),
                after_timestamp=tool_use.input.get("after_timestamp", ""),
                account=tool_use.input.get("account", ""),
                query=tool_use.input.get("query", ""),
            )
            return ToolResult(
                tool_use_id=tool_use.id,
                content=json.dumps(result),
                is_error=False,
            )
        except Exception as e:
            return ToolResult(
                tool_use_id=tool_use.id,
                content=json.dumps({"error": str(e)}),
                is_error=True,
            )

    if tool_use.name == "get_current_timestamp":
        return ToolResult(
            tool_use_id=tool_use.id,
            content=json.dumps(_get_current_timestamp()),
            is_error=False,
        )

    return ToolResult(
        tool_use_id=tool_use.id,
        content=json.dumps({"error": f"Unknown tool: {tool_use.name}"}),
        is_error=True,
    )
