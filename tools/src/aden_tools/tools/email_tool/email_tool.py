"""
Email Tool - Send and reply to emails using multiple providers.

Supports:
- Gmail (GOOGLE_ACCESS_TOKEN, via Aden OAuth2)
- Resend (RESEND_API_KEY)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal

import httpx
import resend
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register email tools with the MCP server."""

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
        except resend.exceptions.ResendError as e:
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
        """Send email using Gmail API (Bearer token pattern, same as HubSpot)."""
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
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
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

    def _get_credential(
        provider: Literal["resend", "gmail"],
        account: str = "",
    ) -> str | None:
        """Get the credential for the requested provider."""
        if provider == "gmail":
            if credentials is not None:
                if account:
                    return credentials.get_by_alias("google", account)
                return credentials.get("google")
            return os.getenv("GOOGLE_ACCESS_TOKEN")
        # resend
        if credentials is not None:
            return credentials.get("resend")
        return os.getenv("RESEND_API_KEY")

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

    def _send_email_impl(
        to: str | list[str],
        subject: str,
        html: str,
        provider: Literal["resend", "gmail"],
        from_email: str | None = None,
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
        account: str = "",
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

        # Resend always requires from_email; Gmail defaults to authenticated user.
        if provider == "resend" and not from_email:
            return {
                "error": "Sender email is required",
                "help": "Pass from_email or set EMAIL_FROM environment variable",
            }

        credential = _get_credential(provider, account)
        if not credential:
            if provider == "gmail":
                return {
                    "error": "Gmail credentials not configured",
                    "help": "Connect Gmail via hive.adenhq.com",
                }
            return {
                "error": "Resend credentials not configured",
                "help": "Set RESEND_API_KEY environment variable. "
                "Get a key at https://resend.com/api-keys",
            }

        try:
            if provider == "gmail":
                return _send_via_gmail(
                    credential, to_list, subject, html, from_email, cc_list, bcc_list
                )
            return _send_via_resend(
                credential, to_list, subject, html, from_email, cc_list, bcc_list
            )
        except Exception as e:
            return {"error": f"Email send failed: {e}"}

    @mcp.tool()
    def send_email(
        to: str | list[str],
        subject: str,
        html: str,
        provider: Literal["resend", "gmail"],
        from_email: str | None = None,
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
        account: str = "",
    ) -> dict:
        """
        Send an email.

        Supports multiple email providers:
        - "gmail": Use Gmail API (requires Gmail OAuth2 via Aden)
        - "resend": Use Resend API (requires RESEND_API_KEY)

        Args:
            to: Recipient email address(es). Single string or list of strings.
            subject: Email subject line (1-998 chars per RFC 2822).
            html: Email body as HTML string.
            provider: Email provider to use ("gmail" or "resend"). Required.
            from_email: Sender email address. Falls back to EMAIL_FROM env var if not provided.
                        Optional for Gmail (defaults to authenticated user's address).
            cc: CC recipient(s). Single string or list of strings. Optional.
            bcc: BCC recipient(s). Single string or list of strings. Optional.
            account: Account alias for multi-account routing (e.g. "timothy-home").
                     Only used with Gmail provider. Optional.

        Returns:
            Dict with send result including provider used and message ID,
            or error dict with "error" and optional "help" keys.
        """
        return _send_email_impl(to, subject, html, provider, from_email, cc, bcc, account)

    def _fetch_original_message(access_token: str, message_id: str) -> dict:
        """Fetch the original message to extract threading info."""
        response = httpx.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            params={"format": "metadata", "metadataHeaders": ["Message-ID", "Subject", "From"]},
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
        }

    @mcp.tool()
    def gmail_reply_email(
        message_id: str,
        html: str,
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
        account: str = "",
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
            account: Account alias for multi-account routing (e.g. "timothy-home").
                     Optional.

        Returns:
            Dict with send result including reply message ID and threadId,
            or error dict with "error" and optional "help" keys.
        """
        import base64
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        if not message_id or not message_id.strip():
            return {"error": "message_id is required"}
        if not html:
            return {"error": "Reply body (html) is required"}

        credential = _get_credential("gmail", account)
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
