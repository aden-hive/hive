"""
Gmail Tool - Read, modify, and manage Gmail messages.

Supports:
- Listing messages with Gmail search queries
- Reading message details (headers, snippet, body)
- Trashing messages
- Modifying labels (star, mark read/unread, etc.)
- Batch message fetching
- Batch label modifications

Requires: GOOGLE_ACCESS_TOKEN (via Aden OAuth2)
"""

from __future__ import annotations

import base64
import os
from typing import TYPE_CHECKING, Literal

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"


def _sanitize_path_param(param: str, param_name: str = "parameter") -> str:
    """Sanitize URL path parameters to prevent path traversal."""
    if "/" in param or ".." in param:
        raise ValueError(f"Invalid {param_name}: cannot contain '/' or '..'")
    return param


def _ensure_list(value: str | list[str] | None) -> list[str] | None:
    """Coerce a bare string to a single-element list.

    LLMs frequently pass ``"STARRED"`` instead of ``["STARRED"]`` for
    list parameters.  This normalises the input so Pydantic validation
    doesn't reject it.
    """
    if isinstance(value, str):
        return [value]
    return value


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register Gmail inbox tools with the MCP server."""

    def _get_token(account: str = "") -> str | None:
        """Get Gmail access token from credentials or environment."""
        if credentials is not None:
            if account:
                return credentials.get_by_alias("google", account)
            return credentials.get("google")
        return os.getenv("GOOGLE_ACCESS_TOKEN")

    def _gmail_request(
        method: str, path: str, access_token: str, **kwargs: object
    ) -> httpx.Response:
        """Make an authenticated Gmail API request."""
        return httpx.request(
            method,
            f"{GMAIL_API_BASE}/{path}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
            **kwargs,
        )

    def _handle_error(response: httpx.Response) -> dict | None:
        """Return error dict for non-200 responses, or None if OK."""
        if response.status_code == 200 or response.status_code == 204:
            return None
        if response.status_code == 401:
            return {
                "error": "Gmail token expired or invalid",
                "help": "Re-authorize via hive.adenhq.com",
            }
        if response.status_code == 404:
            return {"error": "Message not found"}
        return {
            "error": f"Gmail API error (HTTP {response.status_code}): {response.text}",
        }

    def _require_token(account: str = "") -> dict | str:
        """Get token or return error dict."""
        token = _get_token(account)
        if not token:
            return {
                "error": "Gmail credentials not configured",
                "help": "Connect Gmail via hive.adenhq.com",
            }
        return token

    def _parse_headers(headers: list[dict]) -> dict:
        """Extract common headers into a flat dict."""
        result: dict[str, str] = {}
        for h in headers:
            name = h.get("name", "").lower()
            if name in ("subject", "from", "to", "date", "cc"):
                result[name] = h.get("value", "")
        return result

    @mcp.tool()
    def gmail_list_messages(
        query: str = "is:unread",
        max_results: int = 100,
        page_token: str | None = None,
        account: str = "",
    ) -> dict:
        """
        List Gmail messages matching a search query.

        Uses the same query syntax as the Gmail search bar.
        Common queries: "is:unread", "label:INBOX", "from:user@example.com",
        "is:unread label:INBOX", "newer_than:1d".

        Args:
            query: Gmail search query (default: "is:unread").
            max_results: Maximum messages to return (1-500, default 100).
            page_token: Token for fetching the next page of results.
            account: Account alias to target a specific account
                (e.g. "Timothy"). Leave empty for default.

        Returns:
            Dict with "messages" list (each has "id" and "threadId"),
            "result_size_estimate", and optional "next_page_token",
            or error dict.
        """
        token = _require_token(account)
        if isinstance(token, dict):
            return token

        max_results = max(1, min(500, max_results))

        params: dict[str, str | int] = {"q": query, "maxResults": max_results}
        if page_token:
            params["pageToken"] = page_token

        try:
            response = _gmail_request("GET", "messages", token, params=params)
        except httpx.HTTPError as e:
            return {"error": f"Request failed: {e}"}

        error = _handle_error(response)
        if error:
            return error

        data = response.json()
        return {
            "messages": data.get("messages", []),
            "result_size_estimate": data.get("resultSizeEstimate", 0),
            "next_page_token": data.get("nextPageToken"),
        }

    @mcp.tool()
    def gmail_get_message(
        message_id: str,
        format: Literal["full", "metadata", "minimal"] = "metadata",
        account: str = "",
    ) -> dict:
        """
        Get a Gmail message by ID.

        Returns parsed message with headers (subject, from, to, date),
        snippet, labels, and optionally the full body.

        Args:
            message_id: The Gmail message ID.
            format: Response detail level.
                "metadata" (default) - headers + snippet, no body.
                "full" - includes decoded body text.
                "minimal" - IDs and labels only.

        Returns:
            Dict with message details or error dict.
        """
        if not message_id:
            return {"error": "message_id is required"}
        try:
            message_id = _sanitize_path_param(message_id, "message_id")
        except ValueError as e:
            return {"error": str(e)}

        token = _require_token(account)
        if isinstance(token, dict):
            return token

        try:
            response = _gmail_request(
                "GET",
                f"messages/{message_id}",
                token,
                params={"format": format},
            )
        except httpx.HTTPError as e:
            return {"error": f"Request failed: {e}"}

        error = _handle_error(response)
        if error:
            return error

        data = response.json()
        result: dict = {
            "id": data.get("id"),
            "threadId": data.get("threadId"),
            "labels": data.get("labelIds", []),
            "snippet": data.get("snippet", ""),
        }

        # Parse headers if present
        payload = data.get("payload", {})
        headers = payload.get("headers", [])
        if headers:
            result.update(_parse_headers(headers))

        # Decode body for "full" format
        if format == "full":
            body_text = _extract_body(payload)
            if body_text:
                result["body"] = body_text

        return result

    def _extract_body(payload: dict) -> str | None:
        """Extract plain text body from Gmail message payload."""
        # Direct body on payload
        body = payload.get("body", {})
        if body.get("data"):
            try:
                return base64.urlsafe_b64decode(body["data"]).decode("utf-8")
            except Exception:
                pass

        # Multipart: look for text/plain first, then text/html
        parts = payload.get("parts", [])
        for mime_type in ("text/plain", "text/html"):
            for part in parts:
                if part.get("mimeType") == mime_type:
                    part_body = part.get("body", {})
                    if part_body.get("data"):
                        try:
                            return base64.urlsafe_b64decode(part_body["data"]).decode("utf-8")
                        except Exception:
                            pass
        return None

    @mcp.tool()
    def gmail_trash_message(message_id: str, account: str = "") -> dict:
        """
        Move a Gmail message to trash.

        Args:
            message_id: The Gmail message ID to trash.

        Returns:
            Dict with "success" and "message_id", or error dict.
        """
        if not message_id:
            return {"error": "message_id is required"}
        try:
            message_id = _sanitize_path_param(message_id, "message_id")
        except ValueError as e:
            return {"error": str(e)}

        token = _require_token(account)
        if isinstance(token, dict):
            return token

        try:
            response = _gmail_request("POST", f"messages/{message_id}/trash", token)
        except httpx.HTTPError as e:
            return {"error": f"Request failed: {e}"}

        error = _handle_error(response)
        if error:
            return error

        return {"success": True, "message_id": message_id}

    @mcp.tool()
    def gmail_modify_message(
        message_id: str,
        add_labels: str | list[str] | None = None,
        remove_labels: str | list[str] | None = None,
        account: str = "",
    ) -> dict:
        """
        Modify labels on a Gmail message.

        Use this to star, mark read/unread, mark important, or apply custom labels.

        Common label IDs:
        - STARRED, UNREAD, IMPORTANT, SPAM, TRASH
        - INBOX, SENT, DRAFT
        - CATEGORY_PERSONAL, CATEGORY_SOCIAL, CATEGORY_PROMOTIONS

        Examples:
        - Star a message: add_labels=["STARRED"]
        - Mark as read: remove_labels=["UNREAD"]
        - Mark as important: add_labels=["IMPORTANT"]

        Args:
            message_id: The Gmail message ID.
            add_labels: Label IDs to add to the message.
            remove_labels: Label IDs to remove from the message.

        Returns:
            Dict with "success", "message_id", and updated "labels", or error dict.
        """
        add_labels = _ensure_list(add_labels)
        remove_labels = _ensure_list(remove_labels)

        if not message_id:
            return {"error": "message_id is required"}
        try:
            message_id = _sanitize_path_param(message_id, "message_id")
        except ValueError as e:
            return {"error": str(e)}
        token = _require_token(account)
        if isinstance(token, dict):
            return token

        if not add_labels and not remove_labels:
            return {"error": "At least one of add_labels or remove_labels is required"}

        body: dict[str, list[str]] = {}
        if add_labels:
            body["addLabelIds"] = add_labels
        if remove_labels:
            body["removeLabelIds"] = remove_labels

        try:
            response = _gmail_request("POST", f"messages/{message_id}/modify", token, json=body)
        except httpx.HTTPError as e:
            return {"error": f"Request failed: {e}"}

        error = _handle_error(response)
        if error:
            return error

        data = response.json()
        return {
            "success": True,
            "message_id": message_id,
            "labels": data.get("labelIds", []),
        }

    @mcp.tool()
    def gmail_batch_modify_messages(
        message_ids: str | list[str],
        add_labels: str | list[str] | None = None,
        remove_labels: str | list[str] | None = None,
        account: str = "",
    ) -> dict:
        """
        Modify labels on multiple Gmail messages at once.

        Efficient bulk operation for processing many emails. Same label IDs
        as gmail_modify_message.

        Args:
            message_ids: List of Gmail message IDs to modify.
            add_labels: Label IDs to add to all messages.
            remove_labels: Label IDs to remove from all messages.

        Returns:
            Dict with "success" and "count", or error dict.
        """
        message_ids = _ensure_list(message_ids) or []
        add_labels = _ensure_list(add_labels)
        remove_labels = _ensure_list(remove_labels)

        if not message_ids:
            return {"error": "message_ids list is required and must not be empty"}

        token = _require_token(account)
        if isinstance(token, dict):
            return token

        if not add_labels and not remove_labels:
            return {"error": "At least one of add_labels or remove_labels is required"}

        body: dict = {"ids": message_ids}
        if add_labels:
            body["addLabelIds"] = add_labels
        if remove_labels:
            body["removeLabelIds"] = remove_labels

        try:
            response = _gmail_request("POST", "messages/batchModify", token, json=body)
        except httpx.HTTPError as e:
            return {"error": f"Request failed: {e}"}

        # batchModify returns 204 No Content on success
        error = _handle_error(response)
        if error:
            return error

        return {"success": True, "count": len(message_ids)}

    @mcp.tool()
    def gmail_batch_get_messages(
        message_ids: list[str],
        format: Literal["full", "metadata", "minimal"] = "metadata",
        account: str = "",
    ) -> dict:
        """
        Fetch multiple Gmail messages by ID in a single call.

        More efficient than calling gmail_get_message repeatedly. Fetches
        each message internally and returns all results at once.

        Args:
            message_ids: List of Gmail message IDs to fetch (max 50).
            format: Response detail level for all messages.
                "metadata" (default) - headers + snippet, no body.
                "full" - includes decoded body text.
                "minimal" - IDs and labels only.

        Returns:
            Dict with "messages" list, "count", and "errors" list,
            or error dict.
        """
        if not message_ids:
            return {"error": "message_ids list is required and must not be empty"}
        if len(message_ids) > 50:
            return {"error": "Maximum 50 message IDs per call"}

        token = _require_token(account)
        if isinstance(token, dict):
            return token

        messages = []
        errors = []
        for mid in message_ids:
            try:
                mid = _sanitize_path_param(mid, "message_id")
            except ValueError as e:
                errors.append({"message_id": mid, "error": str(e)})
                continue

            try:
                response = _gmail_request(
                    "GET",
                    f"messages/{mid}",
                    token,
                    params={"format": format},
                )
            except httpx.HTTPError as e:
                errors.append({"message_id": mid, "error": f"Request failed: {e}"})
                continue

            error = _handle_error(response)
            if error:
                errors.append({"message_id": mid, **error})
                continue

            data = response.json()
            result: dict = {
                "id": data.get("id"),
                "threadId": data.get("threadId"),
                "labels": data.get("labelIds", []),
                "snippet": data.get("snippet", ""),
            }

            payload = data.get("payload", {})
            headers = payload.get("headers", [])
            if headers:
                result.update(_parse_headers(headers))

            if format == "full":
                body_text = _extract_body(payload)
                if body_text:
                    result["body"] = body_text

            messages.append(result)

        return {"messages": messages, "count": len(messages), "errors": errors}

    @mcp.tool()
    def gmail_create_draft(
        to: str,
        subject: str,
        html: str,
        account: str = "",
    ) -> dict:
        """
        Create a draft email in the user's Gmail Drafts folder.

        The draft can be reviewed and sent manually from Gmail.

        Args:
            to: Recipient email address.
            subject: Email subject line.
            html: Email body as HTML string.

        Returns:
            Dict with "success", "draft_id", and "message_id",
            or error dict with "error" and optional "help" keys.
        """
        if not to or not to.strip():
            return {"error": "Recipient email (to) is required"}
        if not subject or not subject.strip():
            return {"error": "Subject is required"}
        if not html:
            return {"error": "Email body (html) is required"}

        token = _require_token(account)
        if isinstance(token, dict):
            return token

        from email.mime.text import MIMEText

        msg = MIMEText(html, "html")
        msg["To"] = to
        msg["Subject"] = subject

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")

        try:
            response = _gmail_request(
                "POST",
                "drafts",
                token,
                json={"message": {"raw": raw}},
            )
        except httpx.HTTPError as e:
            return {"error": f"Request failed: {e}"}

        error = _handle_error(response)
        if error:
            return error

        data = response.json()
        return {
            "success": True,
            "draft_id": data.get("id", ""),
            "message_id": data.get("message", {}).get("id", ""),
        }

    @mcp.tool()
    def gmail_list_labels(account: str = "") -> dict:
        """
        List all Gmail labels for the user's account.

        Returns both system labels (INBOX, SENT, SPAM, TRASH, etc.) and
        user-created custom labels.

        Returns:
            Dict with "labels" list (each has "id", "name", "type"),
            or error dict.
        """
        token = _require_token(account)
        if isinstance(token, dict):
            return token

        try:
            response = _gmail_request("GET", "labels", token)
        except httpx.HTTPError as e:
            return {"error": f"Request failed: {e}"}

        error = _handle_error(response)
        if error:
            return error

        data = response.json()
        return {"labels": data.get("labels", [])}

    @mcp.tool()
    def gmail_create_label(
        name: str,
        label_list_visibility: Literal["labelShow", "labelShowIfUnread", "labelHide"] = "labelShow",
        message_list_visibility: Literal["show", "hide"] = "show",
        account: str = "",
    ) -> dict:
        """
        Create a new Gmail label.

        Args:
            name: The display name for the new label. Must be unique.
                Supports nesting with "/" separator (e.g. "Agent/Important").
            label_list_visibility: Whether label appears in the label list.
                "labelShow" (default) - always visible.
                "labelShowIfUnread" - only visible when unread mail exists.
                "labelHide" - hidden from label list.
            message_list_visibility: Whether label appears in message list.
                "show" (default) or "hide".

        Returns:
            Dict with "success", "id", "name", and "type", or error dict.
        """
        if not name or not name.strip():
            return {"error": "Label name is required"}

        token = _require_token(account)
        if isinstance(token, dict):
            return token

        body = {
            "name": name,
            "labelListVisibility": label_list_visibility,
            "messageListVisibility": message_list_visibility,
        }

        try:
            response = _gmail_request("POST", "labels", token, json=body)
        except httpx.HTTPError as e:
            return {"error": f"Request failed: {e}"}

        error = _handle_error(response)
        if error:
            return error

        data = response.json()
        return {
            "success": True,
            "id": data.get("id", ""),
            "name": data.get("name", ""),
            "type": data.get("type", "user"),
        }
