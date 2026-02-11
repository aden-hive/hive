"""
Email Tool - Send emails using multiple providers.

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

    def _get_credential(provider: Literal["resend", "gmail"]) -> str | None:
        """Get the credential for the requested provider."""
        if provider == "gmail":
            if credentials is not None:
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

        credential = _get_credential(provider)
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

        Returns:
            Dict with send result including provider used and message ID,
            or error dict with "error" and optional "help" keys.
        """
        return _send_email_impl(to, subject, html, provider, from_email, cc, bcc)
