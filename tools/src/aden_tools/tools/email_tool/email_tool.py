"""
Email Tool - Send and read emails using multiple providers.

Supports:
- Gmail (GOOGLE_ACCESS_TOKEN, via Aden OAuth2) - send + read
- Outlook (MICROSOFT_GRAPH_ACCESS_TOKEN, via Aden OAuth2) - send + read
- Resend (RESEND_API_KEY) - send only

Auto-detection for send: Gmail -> Outlook -> Resend
Auto-detection for read: Gmail -> Outlook
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal

import httpx
import resend
from fastmcp import FastMCP

from aden_tools.utils import GRAPH_BASE, sanitize_path_param

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

# Folder name mapping: canonical name -> (Gmail label ID, Outlook folder name)
_FOLDER_MAP: dict[str, tuple[str, str]] = {
    "INBOX": ("INBOX", "inbox"),
    "SENT": ("SENT", "sentItems"),
    "DRAFTS": ("DRAFT", "drafts"),
    "TRASH": ("TRASH", "deletedItems"),
    "SPAM": ("SPAM", "junkemail"),
}


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register email tools with the MCP server."""

    # ------------------------------------------------------------------ #
    # Helper functions
    # ------------------------------------------------------------------ #

    def _get_credentials() -> dict:
        """Get available email credentials."""
        if credentials is not None:
            return {
                "resend_api_key": credentials.get("resend"),
                "gmail_access_token": credentials.get("google"),
                "outlook_access_token": credentials.get("microsoft_graph"),
            }
        return {
            "resend_api_key": os.getenv("RESEND_API_KEY"),
            "gmail_access_token": os.getenv("GOOGLE_ACCESS_TOKEN"),
            "outlook_access_token": os.getenv("MICROSOFT_GRAPH_ACCESS_TOKEN"),
        }

    def _normalize_folder(folder: str, provider: str) -> str:
        """Map a canonical folder name to the provider-specific name."""
        key = folder.upper()
        if key in _FOLDER_MAP:
            return _FOLDER_MAP[key][0 if provider == "gmail" else 1]
        # Pass through as-is for custom labels/folders
        return folder

    def _resolve_from_email(from_email: str | None) -> str | None:
        """Resolve sender address: explicit param > EMAIL_FROM env var."""
        if from_email:
            return from_email
        return os.getenv("EMAIL_FROM")

    def _normalize_recipients(
        value: str | list[str] | None,
    ) -> list[str] | None:
        """Normalize a recipient value to a list or None."""
        if value is None:
            return None
        if isinstance(value, str):
            return [value] if value.strip() else None
        filtered = [v for v in value if isinstance(v, str) and v.strip()]
        return filtered if filtered else None

    # ------------------------------------------------------------------ #
    # Send providers
    # ------------------------------------------------------------------ #

    def _send_via_resend(
        api_key: str,
        to: list[str],
        subject: str,
        html: str,
        from_email: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict:
        """Send email using Resend API."""
        resend.api_key = api_key
        try:
            payload: dict = {
                "from": from_email,
                "to": to,
                "subject": subject,
                "html": html,
            }
            if cc:
                payload["cc"] = cc
            if bcc:
                payload["bcc"] = bcc
            email = resend.Emails.send(payload)
            return {
                "success": True,
                "provider": "resend",
                "id": email.get("id", ""),
                "to": to,
                "subject": subject,
            }
        except Exception as e:
            return {"error": f"Resend API error: {e}"}

    def _send_via_gmail(
        access_token: str,
        to: list[str],
        subject: str,
        html: str,
        from_email: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict:
        """Send email using Gmail API (Bearer token pattern)."""
        import base64
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("alternative")
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        if from_email:
            msg["From"] = from_email
        if cc:
            msg["Cc"] = ", ".join(cc)
        if bcc:
            msg["Bcc"] = ", ".join(bcc)
        msg.attach(MIMEText(html, "html"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")

        response = httpx.post(
            f"{GMAIL_BASE}/messages/send",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"raw": raw},
            timeout=30.0,
        )

        if response.status_code == 401:
            return {
                "error": "Gmail token expired or invalid",
                "help": "Re-authorize via hive.adenhq.com",
            }
        if response.status_code != 200:
            return {
                "error": f"Gmail API error (HTTP {response.status_code}): {response.text}",
            }

        data = response.json()
        return {
            "success": True,
            "provider": "gmail",
            "id": data.get("id", ""),
            "to": to,
            "subject": subject,
        }

    def _send_via_outlook(
        access_token: str,
        to: list[str],
        subject: str,
        html: str,
        from_email: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict:
        """Send email using Microsoft Graph API."""
        message: dict = {
            "subject": subject,
            "body": {"contentType": "html", "content": html},
            "toRecipients": [{"emailAddress": {"address": addr}} for addr in to],
        }
        if from_email:
            message["from"] = {"emailAddress": {"address": from_email}}
        if cc:
            message["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc]
        if bcc:
            message["bccRecipients"] = [{"emailAddress": {"address": addr}} for addr in bcc]

        response = httpx.post(
            f"{GRAPH_BASE}/sendMail",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"message": message},
            timeout=30.0,
        )

        if response.status_code == 401:
            return {
                "error": "Outlook token expired or invalid",
                "help": "Re-authorize via hive.adenhq.com",
            }
        if response.status_code not in (200, 202):
            return {
                "error": f"Outlook API error (HTTP {response.status_code}): {response.text}",
            }

        return {
            "success": True,
            "provider": "outlook",
            "id": "",  # Graph sendMail returns 202 with no body
            "to": to,
            "subject": subject,
        }

    # ------------------------------------------------------------------ #
    # Gmail read operations
    # ------------------------------------------------------------------ #

    def _gmail_headers(access_token: str) -> dict:
        return {"Authorization": f"Bearer {access_token}"}

    def _parse_gmail_message(msg: dict) -> dict:
        """Parse a Gmail API message resource into a normalized dict."""
        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        # Extract body
        body_text = ""
        body_html = ""
        attachments: list[dict] = []

        def _walk_parts(parts: list[dict]) -> None:
            nonlocal body_text, body_html
            import base64

            for part in parts:
                mime = part.get("mimeType", "")
                if part.get("parts"):
                    _walk_parts(part["parts"])
                elif mime == "text/plain" and not body_text:
                    data = part.get("body", {}).get("data", "")
                    if data:
                        body_text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                elif mime == "text/html" and not body_html:
                    data = part.get("body", {}).get("data", "")
                    if data:
                        body_html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                elif part.get("filename"):
                    attachments.append(
                        {
                            "name": part["filename"],
                            "size": part.get("body", {}).get("size", 0),
                            "mime_type": mime,
                        }
                    )

        payload = msg.get("payload", {})
        if payload.get("parts"):
            _walk_parts(payload["parts"])
        else:
            # Single-part message
            import base64

            mime = payload.get("mimeType", "")
            data = payload.get("body", {}).get("data", "")
            if data:
                decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                if mime == "text/html":
                    body_html = decoded
                else:
                    body_text = decoded

        return {
            "id": msg.get("id", ""),
            "subject": headers.get("subject", ""),
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "cc": headers.get("cc", ""),
            "date": headers.get("date", ""),
            "snippet": msg.get("snippet", ""),
            "is_read": "UNREAD" not in msg.get("labelIds", []),
            "body_text": body_text,
            "body_html": body_html,
            "attachments": attachments,
        }

    def _list_via_gmail(
        access_token: str, folder: str, max_results: int, unread_only: bool
    ) -> dict:
        """List messages from a Gmail folder."""
        label_id = _normalize_folder(folder, "gmail")
        params: dict = {"labelIds": label_id, "maxResults": min(max_results, 500)}
        if unread_only:
            params["q"] = "is:unread"

        resp = httpx.get(
            f"{GMAIL_BASE}/messages",
            headers=_gmail_headers(access_token),
            params=params,
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {
                "error": "Gmail token expired or invalid",
                "help": "Re-authorize via hive.adenhq.com",
            }
        if resp.status_code != 200:
            return {"error": f"Gmail API error (HTTP {resp.status_code}): {resp.text}"}

        data = resp.json()
        message_stubs = data.get("messages", [])
        total = data.get("resultSizeEstimate", len(message_stubs))

        # Batch-fetch message details
        messages = []
        for stub in message_stubs:
            detail_resp = httpx.get(
                f"{GMAIL_BASE}/messages/{stub['id']}",
                headers=_gmail_headers(access_token),
                params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
                timeout=30.0,
            )
            if detail_resp.status_code == 200:
                msg = detail_resp.json()
                hdrs = {
                    h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])
                }
                messages.append(
                    {
                        "id": msg["id"],
                        "subject": hdrs.get("subject", ""),
                        "from": hdrs.get("from", ""),
                        "date": hdrs.get("date", ""),
                        "snippet": msg.get("snippet", ""),
                        "is_read": "UNREAD" not in msg.get("labelIds", []),
                    }
                )

        return {"messages": messages, "total": total, "provider": "gmail"}

    def _read_via_gmail(access_token: str, message_id: str) -> dict:
        """Read a single Gmail message by ID."""
        resp = httpx.get(
            f"{GMAIL_BASE}/messages/{message_id}",
            headers=_gmail_headers(access_token),
            params={"format": "full"},
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {
                "error": "Gmail token expired or invalid",
                "help": "Re-authorize via hive.adenhq.com",
            }
        if resp.status_code == 404:
            return {"error": f"Message not found: {message_id}"}
        if resp.status_code != 200:
            return {"error": f"Gmail API error (HTTP {resp.status_code}): {resp.text}"}

        parsed = _parse_gmail_message(resp.json())
        parsed["provider"] = "gmail"
        return parsed

    def _search_via_gmail(access_token: str, query: str, max_results: int) -> dict:
        """Search Gmail messages."""
        resp = httpx.get(
            f"{GMAIL_BASE}/messages",
            headers=_gmail_headers(access_token),
            params={"q": query, "maxResults": min(max_results, 500)},
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {
                "error": "Gmail token expired or invalid",
                "help": "Re-authorize via hive.adenhq.com",
            }
        if resp.status_code != 200:
            return {"error": f"Gmail API error (HTTP {resp.status_code}): {resp.text}"}

        data = resp.json()
        message_stubs = data.get("messages", [])
        total = data.get("resultSizeEstimate", len(message_stubs))

        messages = []
        for stub in message_stubs:
            detail_resp = httpx.get(
                f"{GMAIL_BASE}/messages/{stub['id']}",
                headers=_gmail_headers(access_token),
                params={"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
                timeout=30.0,
            )
            if detail_resp.status_code == 200:
                msg = detail_resp.json()
                hdrs = {
                    h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])
                }
                messages.append(
                    {
                        "id": msg["id"],
                        "subject": hdrs.get("subject", ""),
                        "from": hdrs.get("from", ""),
                        "date": hdrs.get("date", ""),
                        "snippet": msg.get("snippet", ""),
                        "is_read": "UNREAD" not in msg.get("labelIds", []),
                    }
                )

        return {"messages": messages, "total": total, "provider": "gmail"}

    def _labels_via_gmail(access_token: str) -> dict:
        """List Gmail labels."""
        resp = httpx.get(
            f"{GMAIL_BASE}/labels",
            headers=_gmail_headers(access_token),
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {
                "error": "Gmail token expired or invalid",
                "help": "Re-authorize via hive.adenhq.com",
            }
        if resp.status_code != 200:
            return {"error": f"Gmail API error (HTTP {resp.status_code}): {resp.text}"}

        data = resp.json()
        labels = [
            {
                "id": label["id"],
                "name": label.get("name", label["id"]),
                "type": label.get("type", "user"),
            }
            for label in data.get("labels", [])
        ]
        return {"labels": labels, "provider": "gmail"}

    # ------------------------------------------------------------------ #
    # Outlook read operations
    # ------------------------------------------------------------------ #

    def _outlook_headers(access_token: str) -> dict:
        return {"Authorization": f"Bearer {access_token}"}

    def _parse_outlook_message(msg: dict, *, full: bool = False) -> dict:
        """Parse an Outlook Graph message into a normalized dict."""
        result: dict = {
            "id": msg.get("id", ""),
            "subject": msg.get("subject", ""),
            "from": msg.get("from", {}).get("emailAddress", {}).get("address", ""),
            "date": msg.get("receivedDateTime", ""),
            "snippet": msg.get("bodyPreview", ""),
            "is_read": msg.get("isRead", False),
        }
        if full:
            to_addrs = [
                r.get("emailAddress", {}).get("address", "") for r in msg.get("toRecipients", [])
            ]
            cc_addrs = [
                r.get("emailAddress", {}).get("address", "") for r in msg.get("ccRecipients", [])
            ]
            body = msg.get("body", {})
            result.update(
                {
                    "to": ", ".join(to_addrs),
                    "cc": ", ".join(cc_addrs),
                    "body_text": body.get("content", "")
                    if body.get("contentType") == "text"
                    else "",
                    "body_html": body.get("content", "")
                    if body.get("contentType") == "html"
                    else "",
                    "attachments": [
                        {
                            "name": att.get("name", ""),
                            "size": att.get("size", 0),
                            "mime_type": att.get("contentType", ""),
                        }
                        for att in msg.get("attachments", [])
                    ],
                }
            )
        return result

    def _list_via_outlook(
        access_token: str, folder: str, max_results: int, unread_only: bool
    ) -> dict:
        """List messages from an Outlook folder."""
        folder_name = _normalize_folder(folder, "outlook")
        try:
            folder_name = sanitize_path_param(folder_name, "folder")
        except ValueError as e:
            return {"error": str(e)}
        params: dict = {
            "$top": min(max_results, 500),
            "$orderby": "receivedDateTime desc",
            "$select": "id,subject,from,receivedDateTime,bodyPreview,isRead",
        }
        if unread_only:
            params["$filter"] = "isRead eq false"

        resp = httpx.get(
            f"{GRAPH_BASE}/mailFolders/{folder_name}/messages",
            headers=_outlook_headers(access_token),
            params=params,
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {
                "error": "Outlook token expired or invalid",
                "help": "Re-authorize via hive.adenhq.com",
            }
        if resp.status_code != 200:
            return {"error": f"Outlook API error (HTTP {resp.status_code}): {resp.text}"}

        data = resp.json()
        messages = [_parse_outlook_message(m) for m in data.get("value", [])]
        return {"messages": messages, "total": len(messages), "provider": "outlook"}

    def _read_via_outlook(access_token: str, message_id: str) -> dict:
        """Read a single Outlook message by ID."""
        resp = httpx.get(
            f"{GRAPH_BASE}/messages/{message_id}",
            headers=_outlook_headers(access_token),
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {
                "error": "Outlook token expired or invalid",
                "help": "Re-authorize via hive.adenhq.com",
            }
        if resp.status_code == 404:
            return {"error": f"Message not found: {message_id}"}
        if resp.status_code != 200:
            return {"error": f"Outlook API error (HTTP {resp.status_code}): {resp.text}"}

        parsed = _parse_outlook_message(resp.json(), full=True)
        parsed["provider"] = "outlook"
        return parsed

    def _search_via_outlook(access_token: str, query: str, max_results: int) -> dict:
        """Search Outlook messages."""
        resp = httpx.get(
            f"{GRAPH_BASE}/messages",
            headers=_outlook_headers(access_token),
            params={
                "$search": f'"{query}"',
                "$top": min(max_results, 500),
                "$select": "id,subject,from,receivedDateTime,bodyPreview,isRead",
            },
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {
                "error": "Outlook token expired or invalid",
                "help": "Re-authorize via hive.adenhq.com",
            }
        if resp.status_code != 200:
            return {"error": f"Outlook API error (HTTP {resp.status_code}): {resp.text}"}

        data = resp.json()
        messages = [_parse_outlook_message(m) for m in data.get("value", [])]
        return {"messages": messages, "total": len(messages), "provider": "outlook"}

    def _labels_via_outlook(access_token: str) -> dict:
        """List Outlook mail folders."""
        resp = httpx.get(
            f"{GRAPH_BASE}/mailFolders",
            headers=_outlook_headers(access_token),
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {
                "error": "Outlook token expired or invalid",
                "help": "Re-authorize via hive.adenhq.com",
            }
        if resp.status_code != 200:
            return {"error": f"Outlook API error (HTTP {resp.status_code}): {resp.text}"}

        data = resp.json()
        well_known = {
            "Inbox",
            "Sent Items",
            "Drafts",
            "Deleted Items",
            "Junk Email",
            "Archive",
            "Outbox",
        }
        labels = [
            {
                "id": folder["id"],
                "name": folder.get("displayName", folder["id"]),
                "type": "system" if folder.get("displayName", "") in well_known else "user",
            }
            for folder in data.get("value", [])
        ]
        return {"labels": labels, "provider": "outlook"}

    # ------------------------------------------------------------------ #
    # Write operation helpers
    # ------------------------------------------------------------------ #

    def _mark_read_gmail(access_token: str, message_id: str, read: bool) -> dict:
        """Mark a Gmail message as read or unread."""
        body: dict = {}
        if read:
            body["removeLabelIds"] = ["UNREAD"]
        else:
            body["addLabelIds"] = ["UNREAD"]

        resp = httpx.post(
            f"{GMAIL_BASE}/messages/{message_id}/modify",
            headers=_gmail_headers(access_token),
            json=body,
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {
                "error": "Gmail token expired or invalid",
                "help": "Re-authorize via hive.adenhq.com",
            }
        if resp.status_code != 200:
            return {"error": f"Gmail API error (HTTP {resp.status_code}): {resp.text}"}
        return {"success": True, "provider": "gmail", "message_id": message_id, "is_read": read}

    def _mark_read_outlook(access_token: str, message_id: str, read: bool) -> dict:
        """Mark an Outlook message as read or unread."""
        resp = httpx.patch(
            f"{GRAPH_BASE}/messages/{message_id}",
            headers={**_outlook_headers(access_token), "Content-Type": "application/json"},
            json={"isRead": read},
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {
                "error": "Outlook token expired or invalid",
                "help": "Re-authorize via hive.adenhq.com",
            }
        if resp.status_code != 200:
            return {"error": f"Outlook API error (HTTP {resp.status_code}): {resp.text}"}
        return {"success": True, "provider": "outlook", "message_id": message_id, "is_read": read}

    def _delete_gmail(access_token: str, message_id: str, permanent: bool) -> dict:
        """Delete or trash a Gmail message."""
        if permanent:
            resp = httpx.delete(
                f"{GMAIL_BASE}/messages/{message_id}",
                headers=_gmail_headers(access_token),
                timeout=30.0,
            )
            expected = 204
        else:
            resp = httpx.post(
                f"{GMAIL_BASE}/messages/{message_id}/trash",
                headers=_gmail_headers(access_token),
                timeout=30.0,
            )
            expected = 200
        if resp.status_code == 401:
            return {
                "error": "Gmail token expired or invalid",
                "help": "Re-authorize via hive.adenhq.com",
            }
        if resp.status_code != expected:
            return {"error": f"Gmail API error (HTTP {resp.status_code}): {resp.text}"}
        return {
            "success": True,
            "provider": "gmail",
            "message_id": message_id,
            "permanent": permanent,
        }

    def _delete_outlook(access_token: str, message_id: str, permanent: bool) -> dict:
        """Delete or trash an Outlook message."""
        if permanent:
            resp = httpx.delete(
                f"{GRAPH_BASE}/messages/{message_id}",
                headers=_outlook_headers(access_token),
                timeout=30.0,
            )
            if resp.status_code == 401:
                return {
                    "error": "Outlook token expired or invalid",
                    "help": "Re-authorize via hive.adenhq.com",
                }
            if resp.status_code != 204:
                return {"error": f"Outlook API error (HTTP {resp.status_code}): {resp.text}"}
        else:
            resp = httpx.post(
                f"{GRAPH_BASE}/messages/{message_id}/move",
                headers={**_outlook_headers(access_token), "Content-Type": "application/json"},
                json={"destinationId": "deletedItems"},
                timeout=30.0,
            )
            if resp.status_code == 401:
                return {
                    "error": "Outlook token expired or invalid",
                    "help": "Re-authorize via hive.adenhq.com",
                }
            if resp.status_code not in (200, 201):
                return {"error": f"Outlook API error (HTTP {resp.status_code}): {resp.text}"}
        return {
            "success": True,
            "provider": "outlook",
            "message_id": message_id,
            "permanent": permanent,
        }

    def _reply_gmail(access_token: str, message_id: str, body: str, reply_all: bool) -> dict:
        """Reply to a Gmail message."""
        import base64
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        # Single metadata fetch for threading + recipient info
        original = _fetch_original_message(access_token, message_id)
        if "error" in original:
            return original

        thread_id = original.get("thread_id", "")

        msg = MIMEMultipart("alternative")
        subject = original.get("subject", "")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        msg["Subject"] = subject
        msg["In-Reply-To"] = original.get("message_id_header", "")
        msg["References"] = original.get("message_id_header", "")

        # Set recipients
        original_from = original.get("from", "")
        if reply_all:
            msg["To"] = original_from
            all_to = [a.strip() for a in original.get("to", "").split(",") if a.strip()]
            all_cc = [a.strip() for a in original.get("cc", "").split(",") if a.strip()]
            if all_to:
                msg["Cc"] = ", ".join(all_to + all_cc)
        else:
            msg["To"] = original_from

        msg.attach(MIMEText(body, "html"))
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")

        resp = httpx.post(
            f"{GMAIL_BASE}/messages/send",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"raw": raw, "threadId": thread_id},
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {
                "error": "Gmail token expired or invalid",
                "help": "Re-authorize via hive.adenhq.com",
            }
        if resp.status_code != 200:
            return {"error": f"Gmail API error (HTTP {resp.status_code}): {resp.text}"}

        data = resp.json()
        return {
            "success": True,
            "provider": "gmail",
            "message_id": data.get("id", ""),
            "thread_id": thread_id,
            "reply_all": reply_all,
        }

    def _reply_outlook(access_token: str, message_id: str, body: str, reply_all: bool) -> dict:
        """Reply to an Outlook message."""
        action = "replyAll" if reply_all else "reply"
        resp = httpx.post(
            f"{GRAPH_BASE}/messages/{message_id}/{action}",
            headers={**_outlook_headers(access_token), "Content-Type": "application/json"},
            json={"comment": body},
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {
                "error": "Outlook token expired or invalid",
                "help": "Re-authorize via hive.adenhq.com",
            }
        if resp.status_code not in (200, 202):
            return {"error": f"Outlook API error (HTTP {resp.status_code}): {resp.text}"}
        return {
            "success": True,
            "provider": "outlook",
            "message_id": message_id,
            "reply_all": reply_all,
        }

    def _forward_gmail(access_token: str, message_id: str, to: str, body: str) -> dict:
        """Forward a Gmail message."""
        import base64
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        # Fetch original message
        original = _read_via_gmail(access_token, message_id)
        if "error" in original:
            return original

        msg = MIMEMultipart("alternative")
        subject = original.get("subject", "")
        if not subject.lower().startswith("fwd:"):
            subject = f"Fwd: {subject}"
        msg["Subject"] = subject
        msg["To"] = to

        # Build forwarded content
        original_body = original.get("body_html") or original.get("body_text", "")
        separator = "<br>---------- Forwarded message ----------<br>"
        fwd_header = (
            f"From: {original.get('from', '')}<br>"
            f"Date: {original.get('date', '')}<br>"
            f"Subject: {original.get('subject', '')}<br>"
            f"To: {original.get('to', '')}<br>"
        )
        full_body = (
            f"{body}<br>{separator}{fwd_header}<br>{original_body}"
            if body
            else f"{separator}{fwd_header}<br>{original_body}"
        )
        msg.attach(MIMEText(full_body, "html"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        resp = httpx.post(
            f"{GMAIL_BASE}/messages/send",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            json={"raw": raw},
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {
                "error": "Gmail token expired or invalid",
                "help": "Re-authorize via hive.adenhq.com",
            }
        if resp.status_code != 200:
            return {"error": f"Gmail API error (HTTP {resp.status_code}): {resp.text}"}

        data = resp.json()
        return {
            "success": True,
            "provider": "gmail",
            "message_id": data.get("id", ""),
            "forwarded_to": to,
        }

    def _forward_outlook(access_token: str, message_id: str, to: str, body: str) -> dict:
        """Forward an Outlook message."""
        resp = httpx.post(
            f"{GRAPH_BASE}/messages/{message_id}/forward",
            headers={**_outlook_headers(access_token), "Content-Type": "application/json"},
            json={
                "comment": body,
                "toRecipients": [{"emailAddress": {"address": to}}],
            },
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {
                "error": "Outlook token expired or invalid",
                "help": "Re-authorize via hive.adenhq.com",
            }
        if resp.status_code not in (200, 202):
            return {"error": f"Outlook API error (HTTP {resp.status_code}): {resp.text}"}
        return {
            "success": True,
            "provider": "outlook",
            "message_id": message_id,
            "forwarded_to": to,
        }

    def _move_gmail(access_token: str, message_id: str, destination: str) -> dict:
        """Move a Gmail message to a different label."""
        dest_label = _normalize_folder(destination, "gmail")
        resp = httpx.post(
            f"{GMAIL_BASE}/messages/{message_id}/modify",
            headers=_gmail_headers(access_token),
            json={"addLabelIds": [dest_label], "removeLabelIds": ["INBOX"]},
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {
                "error": "Gmail token expired or invalid",
                "help": "Re-authorize via hive.adenhq.com",
            }
        if resp.status_code != 200:
            return {"error": f"Gmail API error (HTTP {resp.status_code}): {resp.text}"}
        return {
            "success": True,
            "provider": "gmail",
            "message_id": message_id,
            "destination": destination,
        }

    def _move_outlook(access_token: str, message_id: str, destination: str) -> dict:
        """Move an Outlook message to a different folder."""
        folder_name = _normalize_folder(destination, "outlook")
        resp = httpx.post(
            f"{GRAPH_BASE}/messages/{message_id}/move",
            headers={**_outlook_headers(access_token), "Content-Type": "application/json"},
            json={"destinationId": folder_name},
            timeout=30.0,
        )
        if resp.status_code == 401:
            return {
                "error": "Outlook token expired or invalid",
                "help": "Re-authorize via hive.adenhq.com",
            }
        if resp.status_code not in (200, 201):
            return {"error": f"Outlook API error (HTTP {resp.status_code}): {resp.text}"}
        return {
            "success": True,
            "provider": "outlook",
            "message_id": message_id,
            "destination": destination,
        }

    def _bulk_delete_gmail(access_token: str, message_ids: list[str], permanent: bool) -> dict:
        """Bulk delete or trash Gmail messages."""
        if permanent:
            resp = httpx.post(
                f"{GMAIL_BASE}/messages/batchDelete",
                headers=_gmail_headers(access_token),
                json={"ids": message_ids},
                timeout=30.0,
            )
            if resp.status_code == 401:
                return {
                    "error": "Gmail token expired or invalid",
                    "help": "Re-authorize via hive.adenhq.com",
                }
            if resp.status_code != 204:
                return {"error": f"Gmail API error (HTTP {resp.status_code}): {resp.text}"}
        else:
            for mid in message_ids:
                result = _delete_gmail(access_token, mid, permanent=False)
                if "error" in result:
                    return result
        return {
            "success": True,
            "provider": "gmail",
            "deleted_count": len(message_ids),
            "permanent": permanent,
        }

    def _bulk_delete_outlook(access_token: str, message_ids: list[str], permanent: bool) -> dict:
        """Bulk delete or trash Outlook messages."""
        for mid in message_ids:
            result = _delete_outlook(access_token, mid, permanent=permanent)
            if "error" in result:
                return result
        return {
            "success": True,
            "provider": "outlook",
            "deleted_count": len(message_ids),
            "permanent": permanent,
        }

    # ------------------------------------------------------------------ #
    # Send implementation
    # ------------------------------------------------------------------ #

    def _send_email_impl(
        to: str | list[str],
        subject: str,
        html: str,
        from_email: str | None = None,
        provider: Literal["auto", "resend", "gmail", "outlook"] = "auto",
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
    ) -> dict:
        """Core email sending logic, callable by other tools."""
        from_email = _resolve_from_email(from_email)

        to_list = _normalize_recipients(to)
        if not to_list:
            return {"error": "At least one recipient email is required"}
        if not subject or len(subject) > 998:
            return {"error": "Subject must be 1-998 characters"}
        if not html:
            return {"error": "Email body (html) is required"}

        cc_list = _normalize_recipients(cc)
        bcc_list = _normalize_recipients(bcc)

        # Testing override: redirect all recipients to a single address.
        # Set EMAIL_OVERRIDE_TO=you@example.com to intercept all outbound mail.
        override_to = os.getenv("EMAIL_OVERRIDE_TO")
        if override_to:
            original_to = to_list
            to_list = [override_to]
            cc_list = None
            bcc_list = None
            subject = f"[TEST -> {', '.join(original_to)}] {subject}"

        creds = _get_credentials()
        gmail_available = bool(creds["gmail_access_token"])
        outlook_available = bool(creds["outlook_access_token"])
        resend_available = bool(creds["resend_api_key"])

        # Gmail/Outlook don't require from_email (defaults to authenticated user).
        # Resend always requires it.
        needs_from_email = provider == "resend" or (
            provider == "auto"
            and not gmail_available
            and not outlook_available
            and resend_available
        )
        if not from_email and needs_from_email:
            return {
                "error": "Sender email is required",
                "help": "Pass from_email or set EMAIL_FROM environment variable",
            }

        match provider:
            case "gmail":
                if not gmail_available:
                    return {
                        "error": "Gmail credentials not configured",
                        "help": "Connect Gmail via hive.adenhq.com",
                    }
                return _send_via_gmail(
                    creds["gmail_access_token"],
                    to_list,
                    subject,
                    html,
                    from_email,
                    cc_list,
                    bcc_list,
                )
            case "outlook":
                if not outlook_available:
                    return {
                        "error": "Outlook credentials not configured",
                        "help": "Connect Outlook via hive.adenhq.com",
                    }
                return _send_via_outlook(
                    creds["outlook_access_token"],
                    to_list,
                    subject,
                    html,
                    from_email,
                    cc_list,
                    bcc_list,
                )
            case "resend":
                if not resend_available:
                    return {
                        "error": "Resend credentials not configured",
                        "help": "Set RESEND_API_KEY environment variable. "
                        "Get a key at https://resend.com/api-keys",
                    }
                return _send_via_resend(
                    creds["resend_api_key"], to_list, subject, html, from_email, cc_list, bcc_list
                )
            case _:  # auto: Gmail first, then Outlook, then Resend
                if gmail_available:
                    return _send_via_gmail(
                        creds["gmail_access_token"],
                        to_list,
                        subject,
                        html,
                        from_email,
                        cc_list,
                        bcc_list,
                    )
                if outlook_available:
                    return _send_via_outlook(
                        creds["outlook_access_token"],
                        to_list,
                        subject,
                        html,
                        from_email,
                        cc_list,
                        bcc_list,
                    )
                if resend_available:
                    return _send_via_resend(
                        creds["resend_api_key"],
                        to_list,
                        subject,
                        html,
                        from_email,
                        cc_list,
                        bcc_list,
                    )
                return {
                    "error": "No email credentials configured",
                    "help": "Set RESEND_API_KEY, connect Gmail,"
                    " or connect Outlook via hive.adenhq.com",
                }

    # ------------------------------------------------------------------ #
    # Read provider resolution
    # ------------------------------------------------------------------ #

    def _resolve_read_provider(
        provider: Literal["auto", "gmail", "outlook"],
    ) -> tuple[str | None, dict | None]:
        """Resolve which read provider to use. Returns (provider_name, error_dict)."""
        creds = _get_credentials()
        gmail_available = bool(creds["gmail_access_token"])
        outlook_available = bool(creds["outlook_access_token"])

        match provider:
            case "gmail":
                if not gmail_available:
                    return None, {
                        "error": "Gmail credentials not configured",
                        "help": "Connect Gmail via hive.adenhq.com",
                    }
                return "gmail", None
            case "outlook":
                if not outlook_available:
                    return None, {
                        "error": "Outlook credentials not configured",
                        "help": "Connect Outlook via hive.adenhq.com",
                    }
                return "outlook", None
            case _:  # auto: Gmail first, then Outlook
                if gmail_available:
                    return "gmail", None
                if outlook_available:
                    return "outlook", None
                return None, {
                    "error": "No email read credentials configured",
                    "help": "Connect Gmail or Outlook via hive.adenhq.com",
                }

    # ------------------------------------------------------------------ #
    # MCP Tools - Send
    # ------------------------------------------------------------------ #

    @mcp.tool()
    def send_email(
        to: str | list[str],
        subject: str,
        html: str,
        from_email: str | None = None,
        provider: Literal["auto", "resend", "gmail", "outlook"] = "auto",
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
    ) -> dict:
        """
        Send an email.

        Supports multiple email providers:
        - "auto": Tries Gmail first, then Outlook, then Resend (default)
        - "gmail": Use Gmail API (requires Gmail OAuth2 via Aden)
        - "outlook": Use Outlook/Microsoft 365 (requires Outlook OAuth2 via Aden)
        - "resend": Use Resend API (requires RESEND_API_KEY)

        Args:
            to: Recipient email address(es). Single string or list of strings.
            subject: Email subject line (1-998 chars per RFC 2822).
            html: Email body as HTML string.
            from_email: Sender email address. Falls back to EMAIL_FROM env var if not provided.
                        Optional for Gmail/Outlook (defaults to authenticated user's address).
            provider: Email provider to use ("auto", "gmail", "outlook", or "resend").
            cc: CC recipient(s). Single string or list of strings. Optional.
            bcc: BCC recipient(s). Single string or list of strings. Optional.

        Returns:
            Dict with send result including provider used and message ID,
            or error dict with "error" and optional "help" keys.
        """
        return _send_email_impl(to, subject, html, from_email, provider, cc, bcc)

    def _fetch_original_message(access_token: str, message_id: str) -> dict:
        """Fetch the original message to extract threading and recipient info."""
        response = httpx.get(
            f"{GMAIL_BASE}/messages/{message_id}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            params={
                "format": "metadata",
                "metadataHeaders": ["Message-ID", "Subject", "From", "To", "Cc"],
            },
            timeout=30.0,
        )

        if response.status_code == 401:
            return {
                "error": "Gmail token expired or invalid",
                "help": "Re-authorize via hive.adenhq.com",
            }
        if response.status_code == 404:
            return {"error": f"Original message not found: {message_id}"}
        if response.status_code != 200:
            return {
                "error": f"Gmail API error (HTTP {response.status_code}): {response.text}",
            }

        data = response.json()
        headers = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
        return {
            "thread_id": data.get("threadId"),
            "message_id_header": headers.get("Message-ID", headers.get("Message-Id", "")),
            "subject": headers.get("Subject", ""),
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "cc": headers.get("Cc", ""),
        }

    @mcp.tool()
    def gmail_reply_email(
        message_id: str,
        html: str,
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
    ) -> dict:
        """
        Reply to a Gmail message, keeping it in the same thread.

        Fetches the original message to get threading info (threadId, Message-ID,
        subject, sender), then sends a reply with proper In-Reply-To and References
        headers so it appears as a threaded reply in Gmail.

        Args:
            message_id: The Gmail message ID to reply to.
            html: Reply body as HTML string.
            cc: CC recipient(s). Single string or list of strings. Optional.
            bcc: BCC recipient(s). Single string or list of strings. Optional.

        Returns:
            Dict with send result including reply message ID and threadId,
            or error dict with "error" and optional "help" keys.
        """
        import base64
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        if not message_id or not message_id.strip():
            return {"error": "message_id is required"}
        try:
            message_id = sanitize_path_param(message_id, "message_id")
        except ValueError as e:
            return {"error": str(e)}
        if not html:
            return {"error": "Reply body (html) is required"}

        creds = _get_credentials()
        credential = creds["gmail_access_token"]
        if not credential:
            return {
                "error": "Gmail credentials not configured",
                "help": "Connect Gmail via hive.adenhq.com",
            }

        # Fetch original message for threading info
        try:
            original = _fetch_original_message(credential, message_id)
        except httpx.HTTPError as e:
            return {"error": f"Failed to fetch original message: {e}"}

        if "error" in original:
            return original

        thread_id = original["thread_id"]
        original_message_id = original["message_id_header"]
        original_subject = original["subject"]
        reply_to_address = original["from"]

        # Build reply subject
        subject = original_subject
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        # Build MIME message with threading headers
        msg = MIMEMultipart("alternative")
        msg["To"] = reply_to_address
        msg["Subject"] = subject
        if original_message_id:
            msg["In-Reply-To"] = original_message_id
            msg["References"] = original_message_id

        cc_list = _normalize_recipients(cc)
        bcc_list = _normalize_recipients(bcc)
        if cc_list:
            msg["Cc"] = ", ".join(cc_list)
        if bcc_list:
            msg["Bcc"] = ", ".join(bcc_list)

        msg.attach(MIMEText(html, "html"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")

        # Testing override
        override_to = os.getenv("EMAIL_OVERRIDE_TO")
        if override_to:
            # Rebuild with overridden recipient
            msg.replace_header("To", override_to)
            if "Cc" in msg:
                del msg["Cc"]
            if "Bcc" in msg:
                del msg["Bcc"]
            msg.replace_header("Subject", f"[TEST -> {reply_to_address}] {subject}")
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")

        try:
            response = httpx.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                headers={
                    "Authorization": f"Bearer {credential}",
                    "Content-Type": "application/json",
                },
                json={"raw": raw, "threadId": thread_id},
                timeout=30.0,
            )
        except httpx.HTTPError as e:
            return {"error": f"Failed to send reply: {e}"}

        if response.status_code == 401:
            return {
                "error": "Gmail token expired or invalid",
                "help": "Re-authorize via hive.adenhq.com",
            }
        if response.status_code != 200:
            return {
                "error": f"Gmail API error (HTTP {response.status_code}): {response.text}",
            }

        data = response.json()
        return {
            "success": True,
            "provider": "gmail",
            "id": data.get("id", ""),
            "threadId": data.get("threadId", ""),
            "to": reply_to_address,
            "subject": subject,
        }

    # ------------------------------------------------------------------ #
    # MCP Tools - Read
    # ------------------------------------------------------------------ #

    @mcp.tool()
    def email_list(
        folder: str = "INBOX",
        max_results: int = 10,
        unread_only: bool = False,
        provider: Literal["auto", "gmail", "outlook"] = "auto",
    ) -> dict:
        """
        List emails in a folder.

        Retrieves a list of email message summaries from the specified folder.
        Use canonical folder names: INBOX, SENT, DRAFTS, TRASH, SPAM.
        Custom labels/folders can also be used with provider-specific names.

        Args:
            folder: Folder to list messages from (default: "INBOX").
                    Canonical names (INBOX, SENT, DRAFTS, TRASH, SPAM) are
                    automatically mapped to provider-specific names.
            max_results: Maximum number of messages to return (default: 10, max: 500).
            unread_only: If True, only return unread messages.
            provider: Email provider ("auto", "gmail", or "outlook").

        Returns:
            Dict with "messages" list, "total" count, and "provider" used,
            or error dict with "error" and optional "help" keys.
        """
        resolved, err = _resolve_read_provider(provider)
        if err:
            return err

        creds = _get_credentials()
        try:
            match resolved:
                case "gmail":
                    return _list_via_gmail(
                        creds["gmail_access_token"], folder, max_results, unread_only
                    )
                case _:
                    return _list_via_outlook(
                        creds["outlook_access_token"], folder, max_results, unread_only
                    )
        except Exception as e:
            return {"error": f"Email list failed: {e}"}

    @mcp.tool()
    def email_read(
        message_id: str,
        provider: Literal["auto", "gmail", "outlook"] = "auto",
    ) -> dict:
        """
        Read a full email message by ID.

        Retrieves the complete email including headers, body (text and HTML),
        and attachment metadata. Use message IDs from email_list or email_search.

        Args:
            message_id: The message ID to read (from email_list or email_search results).
            provider: Email provider ("auto", "gmail", or "outlook").

        Returns:
            Dict with full message details (id, subject, from, to, cc, date,
            body_text, body_html, attachments, provider),
            or error dict with "error" and optional "help" keys.
        """
        if not message_id:
            return {"error": "message_id is required"}
        try:
            message_id = sanitize_path_param(message_id, "message_id")
        except ValueError as e:
            return {"error": str(e)}

        resolved, err = _resolve_read_provider(provider)
        if err:
            return err

        creds = _get_credentials()
        try:
            match resolved:
                case "gmail":
                    return _read_via_gmail(creds["gmail_access_token"], message_id)
                case _:
                    return _read_via_outlook(creds["outlook_access_token"], message_id)
        except Exception as e:
            return {"error": f"Email read failed: {e}"}

    @mcp.tool()
    def email_search(
        query: str,
        max_results: int = 10,
        provider: Literal["auto", "gmail", "outlook"] = "auto",
    ) -> dict:
        """
        Search emails.

        Search syntax depends on the provider:
        - Gmail: Uses Gmail search syntax (e.g., "from:user@example.com is:unread subject:meeting")
        - Outlook: Uses Microsoft Search full-text query (e.g., "meeting notes from john")

        Args:
            query: Search query string. Provider-specific syntax.
            max_results: Maximum number of results to return (default: 10, max: 500).
            provider: Email provider ("auto", "gmail", or "outlook").

        Returns:
            Dict with "messages" list, "total" count, and "provider" used,
            or error dict with "error" and optional "help" keys.
        """
        if not query or not query.strip():
            return {"error": "Search query is required"}

        resolved, err = _resolve_read_provider(provider)
        if err:
            return err

        creds = _get_credentials()
        try:
            match resolved:
                case "gmail":
                    return _search_via_gmail(creds["gmail_access_token"], query, max_results)
                case _:
                    return _search_via_outlook(creds["outlook_access_token"], query, max_results)
        except Exception as e:
            return {"error": f"Email search failed: {e}"}

    @mcp.tool()
    def email_labels(
        provider: Literal["auto", "gmail", "outlook"] = "auto",
    ) -> dict:
        """
        List available email labels or folders.

        Returns all labels (Gmail) or mail folders (Outlook) for the
        authenticated account. Use the returned IDs/names with email_list.

        Args:
            provider: Email provider ("auto", "gmail", or "outlook").

        Returns:
            Dict with "labels" list (each with id, name, type) and "provider" used,
            or error dict with "error" and optional "help" keys.
        """
        resolved, err = _resolve_read_provider(provider)
        if err:
            return err

        creds = _get_credentials()
        try:
            match resolved:
                case "gmail":
                    return _labels_via_gmail(creds["gmail_access_token"])
                case _:
                    return _labels_via_outlook(creds["outlook_access_token"])
        except Exception as e:
            return {"error": f"Email labels failed: {e}"}

    # ------------------------------------------------------------------ #
    # MCP Tools - Write Operations
    # ------------------------------------------------------------------ #

    @mcp.tool()
    def email_mark_read(
        message_id: str,
        read: bool = True,
        provider: Literal["auto", "gmail", "outlook"] = "auto",
    ) -> dict:
        """
        Mark an email as read or unread.

        Args:
            message_id: The message ID (from email_list or email_search results).
            read: True to mark as read, False to mark as unread (default: True).
            provider: Email provider ("auto", "gmail", or "outlook").

        Returns:
            Dict with success status and provider used,
            or error dict with "error" and optional "help" keys.
        """
        if not message_id:
            return {"error": "message_id is required"}
        try:
            message_id = sanitize_path_param(message_id, "message_id")
        except ValueError as e:
            return {"error": str(e)}

        resolved, err = _resolve_read_provider(provider)
        if err:
            return err

        creds = _get_credentials()
        try:
            match resolved:
                case "gmail":
                    return _mark_read_gmail(creds["gmail_access_token"], message_id, read)
                case _:
                    return _mark_read_outlook(creds["outlook_access_token"], message_id, read)
        except Exception as e:
            return {"error": f"Email mark read failed: {e}"}

    @mcp.tool()
    def email_delete(
        message_id: str,
        permanent: bool = False,
        provider: Literal["auto", "gmail", "outlook"] = "auto",
    ) -> dict:
        """
        Delete or trash an email.

        By default moves the message to Trash. Set permanent=True for
        irreversible deletion.

        Args:
            message_id: The message ID to delete.
            permanent: If True, permanently delete. If False, move to Trash (default: False).
            provider: Email provider ("auto", "gmail", or "outlook").

        Returns:
            Dict with success status and provider used,
            or error dict with "error" and optional "help" keys.
        """
        if not message_id:
            return {"error": "message_id is required"}
        try:
            message_id = sanitize_path_param(message_id, "message_id")
        except ValueError as e:
            return {"error": str(e)}

        resolved, err = _resolve_read_provider(provider)
        if err:
            return err

        creds = _get_credentials()
        try:
            match resolved:
                case "gmail":
                    return _delete_gmail(creds["gmail_access_token"], message_id, permanent)
                case _:
                    return _delete_outlook(creds["outlook_access_token"], message_id, permanent)
        except Exception as e:
            return {"error": f"Email delete failed: {e}"}

    @mcp.tool()
    def email_reply(
        message_id: str,
        body: str,
        reply_all: bool = False,
        provider: Literal["auto", "gmail", "outlook"] = "auto",
    ) -> dict:
        """
        Reply to an email.

        Sends a reply to the specified message. For Gmail, constructs a MIME
        reply with proper In-Reply-To/References headers and thread ID.

        Args:
            message_id: The message ID to reply to.
            body: Reply body as HTML string.
            reply_all: If True, reply to all recipients (default: False).
            provider: Email provider ("auto", "gmail", or "outlook").

        Returns:
            Dict with success status and provider used,
            or error dict with "error" and optional "help" keys.
        """
        if not message_id:
            return {"error": "message_id is required"}
        try:
            message_id = sanitize_path_param(message_id, "message_id")
        except ValueError as e:
            return {"error": str(e)}
        if not body or not body.strip():
            return {"error": "Reply body is required"}

        resolved, err = _resolve_read_provider(provider)
        if err:
            return err

        creds = _get_credentials()
        try:
            match resolved:
                case "gmail":
                    return _reply_gmail(creds["gmail_access_token"], message_id, body, reply_all)
                case _:
                    return _reply_outlook(
                        creds["outlook_access_token"], message_id, body, reply_all
                    )
        except Exception as e:
            return {"error": f"Email reply failed: {e}"}

    @mcp.tool()
    def email_forward(
        message_id: str,
        to: str,
        body: str = "",
        provider: Literal["auto", "gmail", "outlook"] = "auto",
    ) -> dict:
        """
        Forward an email to another recipient.

        For Gmail, fetches the original message and constructs a forwarded
        MIME message with the original content below a separator.

        Args:
            message_id: The message ID to forward.
            to: Recipient email address.
            body: Optional message to include above the forwarded content.
            provider: Email provider ("auto", "gmail", or "outlook").

        Returns:
            Dict with success status and provider used,
            or error dict with "error" and optional "help" keys.
        """
        if not message_id:
            return {"error": "message_id is required"}
        try:
            message_id = sanitize_path_param(message_id, "message_id")
        except ValueError as e:
            return {"error": str(e)}
        if not to or not to.strip():
            return {"error": "Recipient email (to) is required"}

        resolved, err = _resolve_read_provider(provider)
        if err:
            return err

        creds = _get_credentials()
        try:
            match resolved:
                case "gmail":
                    return _forward_gmail(creds["gmail_access_token"], message_id, to, body)
                case _:
                    return _forward_outlook(creds["outlook_access_token"], message_id, to, body)
        except Exception as e:
            return {"error": f"Email forward failed: {e}"}

    @mcp.tool()
    def email_move(
        message_id: str,
        destination: str,
        provider: Literal["auto", "gmail", "outlook"] = "auto",
    ) -> dict:
        """
        Move an email to a different folder.

        Use canonical folder names (INBOX, SENT, DRAFTS, TRASH, SPAM) or
        provider-specific labels/folders.

        Args:
            message_id: The message ID to move.
            destination: Target folder name. Canonical names are automatically
                         mapped to provider-specific names.
            provider: Email provider ("auto", "gmail", or "outlook").

        Returns:
            Dict with success status and provider used,
            or error dict with "error" and optional "help" keys.
        """
        if not message_id:
            return {"error": "message_id is required"}
        try:
            message_id = sanitize_path_param(message_id, "message_id")
        except ValueError as e:
            return {"error": str(e)}
        if not destination or not destination.strip():
            return {"error": "Destination folder is required"}

        resolved, err = _resolve_read_provider(provider)
        if err:
            return err

        creds = _get_credentials()
        try:
            match resolved:
                case "gmail":
                    return _move_gmail(creds["gmail_access_token"], message_id, destination)
                case _:
                    return _move_outlook(creds["outlook_access_token"], message_id, destination)
        except Exception as e:
            return {"error": f"Email move failed: {e}"}

    @mcp.tool()
    def email_bulk_delete(
        message_ids: list[str],
        permanent: bool = False,
        provider: Literal["auto", "gmail", "outlook"] = "auto",
    ) -> dict:
        """
        Bulk delete or trash multiple emails.

        For Gmail permanent delete, uses the efficient batchDelete API.
        Otherwise processes messages individually.

        Args:
            message_ids: List of message IDs to delete.
            permanent: If True, permanently delete. If False, move to Trash (default: False).
            provider: Email provider ("auto", "gmail", or "outlook").

        Returns:
            Dict with success status, deleted count, and provider used,
            or error dict with "error" and optional "help" keys.
        """
        if not message_ids:
            return {"success": True, "deleted_count": 0, "permanent": permanent}

        for mid in message_ids:
            try:
                sanitize_path_param(mid, "message_id")
            except ValueError as e:
                return {"error": str(e)}

        resolved, err = _resolve_read_provider(provider)
        if err:
            return err

        creds = _get_credentials()
        try:
            match resolved:
                case "gmail":
                    return _bulk_delete_gmail(creds["gmail_access_token"], message_ids, permanent)
                case _:
                    return _bulk_delete_outlook(
                        creds["outlook_access_token"], message_ids, permanent
                    )
        except Exception as e:
            return {"error": f"Email bulk delete failed: {e}"}
