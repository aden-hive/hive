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
from framework.runner.tool_registry import _execution_context

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
            "Fetch emails from the Gmail inbox and write them to a JSONL file. "
            "Returns the filename of the written file."
        ),
        parameters={
            "type": "object",
            "properties": {
                "max_emails": {
                    "type": "string",
                    "description": "Maximum number of emails to fetch (default '100')",
                },
                "account": {
                    "type": "string",
                    "description": (
                        "Account alias to use (e.g. 'timothy-home'). "
                        "Required when multiple Google accounts are connected."
                    ),
                },
            },
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
            "data_dir not set in execution context. "
            "Is the tool running inside a GraphExecutor?"
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
            token = credentials.get_by_alias("google", account)
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


def _bulk_fetch_emails(max_emails: str = "100", account: str = "") -> str:
    """Fetch inbox emails and write them to emails.jsonl.

    Uses synchronous httpx.Client since this runs as a tool call inside
    an already-running async event loop.

    Args:
        max_emails: Maximum number of emails to fetch.
        account: Account alias (e.g. 'timothy-home') for multi-account routing.

    Returns:
        The filename "emails.jsonl" (written to session data_dir).
    """
    max_count = int(max_emails) if max_emails else 100
    access_token = _get_access_token(account)
    data_dir = _get_data_dir()
    Path(data_dir).mkdir(parents=True, exist_ok=True)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    message_ids: list[str] = []
    page_token: str | None = None

    with httpx.Client(headers=headers, timeout=30.0) as client:
        # Phase 1: Collect message IDs (paginated, sequential)
        while len(message_ids) < max_count:
            remaining = max_count - len(message_ids)
            page_size = min(remaining, 500)

            params: dict[str, str | int] = {
                "q": "label:INBOX",
                "maxResults": page_size,
            }
            if page_token:
                params["pageToken"] = page_token

            resp = client.get(f"{GMAIL_API_BASE}/messages", params=params)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Gmail list failed (HTTP {resp.status_code}): {resp.text}"
                )

            data = resp.json()
            messages = data.get("messages", [])
            if not messages:
                break

            for msg in messages:
                if len(message_ids) >= max_count:
                    break
                message_ids.append(msg["id"])

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        if not message_ids:
            (Path(data_dir) / "emails.jsonl").write_text("", encoding="utf-8")
            logger.info("No inbox emails found.")
            return "emails.jsonl"

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
                        parsed = _parse_headers(
                            raw.get("payload", {}).get("headers", [])
                        )
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
                    logger.warning(
                        f"Failed to fetch {msg_id} after {retries + 1} attempts: {e}"
                    )

    dropped = len(message_ids) - len(emails)
    if dropped > 0:
        logger.warning(
            f"Dropped {dropped}/{len(message_ids)} emails during metadata fetch "
            f"(wrote {len(emails)} to emails.jsonl)"
        )

    # Phase 3: Write JSONL
    output_path = Path(data_dir) / "emails.jsonl"
    with open(output_path, "w", encoding="utf-8") as f:
        for email in emails:
            f.write(json.dumps(email, ensure_ascii=False) + "\n")

    logger.info(
        f"Wrote {len(emails)} emails to emails.jsonl ({output_path.stat().st_size} bytes)"
    )
    return "emails.jsonl"


# ---------------------------------------------------------------------------
# Unified tool executor (auto-discovered by ToolRegistry.discover_from_module)
# ---------------------------------------------------------------------------


def tool_executor(tool_use: ToolUse) -> ToolResult:
    """Dispatch tool calls to their implementations."""
    if tool_use.name == "bulk_fetch_emails":
        try:
            max_emails = tool_use.input.get("max_emails", "100")
            account = tool_use.input.get("account", "")
            filename = _bulk_fetch_emails(max_emails=max_emails, account=account)
            return ToolResult(
                tool_use_id=tool_use.id,
                content=json.dumps({"filename": filename}),
                is_error=False,
            )
        except Exception as e:
            return ToolResult(
                tool_use_id=tool_use.id,
                content=json.dumps({"error": str(e)}),
                is_error=True,
            )

    return ToolResult(
        tool_use_id=tool_use.id,
        content=json.dumps({"error": f"Unknown tool: {tool_use.name}"}),
        is_error=True,
    )
