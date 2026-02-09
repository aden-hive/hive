"""
Email Tool - Send emails using multiple providers.

Supports:
- Gmail (GOOGLE_ACCESS_TOKEN, via Aden OAuth2)
- Resend (RESEND_API_KEY)

Auto-detection: If provider="auto", tries Gmail first, then Resend.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Literal

import httpx
import resend
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


class EmailClient:
    """Standalone email client for direct usage (e.g. by agents)."""

    def __init__(self, credentials: dict | None = None):
        if credentials:
            self.resend_api_key = credentials.get("resend")
            self.gmail_access_token = credentials.get("google")
            self.smtp_config = credentials.get("smtp")
        else:
            self.resend_api_key = os.getenv("RESEND_API_KEY")
            self.gmail_access_token = os.getenv("GOOGLE_ACCESS_TOKEN")
            self.smtp_config = {
                "host": os.getenv("SMTP_HOST"),
                "port": int(os.getenv("SMTP_PORT", "587")),
                "username": os.getenv("SMTP_USERNAME"),
                "password": os.getenv("SMTP_PASSWORD"),
            }

    def _resolve_from_email(self, from_email: str | None) -> str | None:
        if from_email:
            return from_email
        return os.getenv("EMAIL_FROM") or os.getenv("SMTP_USERNAME")

    def _send_via_smtp(
        self,
        to: list[str],
        subject: str,
        html: str,
        from_email: str,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict:
        """Send email using SMTP (e.g. Gmail App Password)."""
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        if not self.smtp_config["host"] or not self.smtp_config["password"]:
            return {"error": "SMTP server/password not configured"}

        msg = MIMEMultipart("alternative")
        msg["From"] = from_email
        msg["To"] = ", ".join(to)
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = ", ".join(cc)
        if bcc:
            msg["Bcc"] = ", ".join(bcc)
        msg.attach(MIMEText(html, "html"))

        try:
            with smtplib.SMTP(self.smtp_config["host"], self.smtp_config["port"]) as server:
                server.starttls()
                server.login(self.smtp_config["username"], self.smtp_config["password"])
                server.send_message(msg)

            return {"success": True, "provider": "smtp", "to": to, "subject": subject}
        except Exception as e:
            return {"error": f"SMTP send failed: {e}"}

    def _send_via_resend(
        self,
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
        self,
        access_token: str,
        to: list[str],
        subject: str,
        html: str,
        from_email: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
    ) -> dict:
        """Send email using Gmail API."""
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

    def _normalize_recipients(self, value: str | list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if isinstance(value, str):
            return [value] if value.strip() else None
        filtered = [v for v in value if isinstance(v, str) and v.strip()]
        return filtered if filtered else None

    def send_email(
        self,
        to: str | list[str],
        subject: str,
        html: str,
        from_email: str | None = None,
        provider: Literal["auto", "resend", "gmail", "smtp"] = "auto",
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
    ) -> dict:
        """Core email sending logic."""
        from_email = self._resolve_from_email(from_email)

        to_list = self._normalize_recipients(to)
        if not to_list:
            return {"error": "At least one recipient email is required"}
        if not subject or len(subject) > 998:
            return {"error": "Subject must be 1-998 characters"}
        if not html:
            return {"error": "Email body (html) is required"}

        cc_list = self._normalize_recipients(cc)
        bcc_list = self._normalize_recipients(bcc)

        override_to = os.getenv("EMAIL_OVERRIDE_TO")
        if override_to:
            original_to = to_list
            to_list = [override_to]
            cc_list = None
            bcc_list = None
            subject = f"[TEST -> {', '.join(original_to)}] {subject}"

        gmail_available = bool(self.gmail_access_token)
        resend_available = bool(self.resend_api_key)
        smtp_available = bool(self.smtp_config.get("host") and self.smtp_config.get("password"))

        # Requirements check
        if provider == "resend" and not from_email:
            return {"error": "Sender email is required for Resend"}

        if not from_email and not gmail_available and (resend_available or smtp_available):
            # Try to resolve from SMTP username if available
            from_email = self.smtp_config.get("username")
            if not from_email:
                return {"error": "Sender email is required"}

        try:
            # 1. Explicit Provider
            if provider == "gmail":
                if not gmail_available:
                    return {"error": "Gmail credentials not configured"}
                return self._send_via_gmail(
                    self.gmail_access_token, to_list, subject, html, from_email, cc_list, bcc_list
                )

            if provider == "resend":
                if not resend_available:
                    return {"error": "Resend credentials not configured"}
                return self._send_via_resend(
                    self.resend_api_key, to_list, subject, html, from_email, cc_list, bcc_list
                )

            if provider == "smtp":
                if not smtp_available:
                    return {"error": "SMTP credentials not configured"}
                return self._send_via_smtp(to_list, subject, html, from_email, cc_list, bcc_list)

            # 2. Auto Provider
            if gmail_available:
                return self._send_via_gmail(
                    self.gmail_access_token, to_list, subject, html, from_email, cc_list, bcc_list
                )

            if resend_available:
                return self._send_via_resend(
                    self.resend_api_key, to_list, subject, html, from_email, cc_list, bcc_list
                )

            if smtp_available:
                return self._send_via_smtp(to_list, subject, html, from_email, cc_list, bcc_list)

            return {
                "error": "No email credentials configured",
                "help": "Set RESEND_API_KEY, GOOGLE_ACCESS_TOKEN, or SMTP_xyz vars",
            }

        except Exception as e:
            return {"error": f"Email send failed: {e}"}


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register email tools with the MCP server."""

    # Initialize client (will capture env vars if credentials is None)
    creds_dict = None
    if credentials:
        creds_dict = {
            "resend": credentials.get("resend"),
            "google": credentials.get("google"),
        }

    client = EmailClient(creds_dict)

    @mcp.tool()
    def send_email(
        to: str | list[str],
        subject: str,
        html: str,
        from_email: str | None = None,
        provider: Literal["auto", "resend", "gmail", "smtp"] = "auto",
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
    ) -> dict:
        """
        Send an email.

        Supports multiple email providers:
        - "auto": Tries Gmail -> Resend -> SMTP (default)
        - "gmail": Use Gmail API
        - "resend": Use Resend API
        - "smtp": Use SMTP (e.g. Gmail App Password)

        Args:
            to: Recipient email address(es). Single string or list of strings.
            subject: Email subject line (1-998 chars per RFC 2822).
            html: Email body as HTML string.
            from_email: Sender email address. Falls back to EMAIL_FROM env var if not provided.
                        Optional for Gmail (defaults to authenticated user's address).
            provider: Email provider to use ("auto", "gmail", or "resend").
            cc: CC recipient(s). Single string or list of strings. Optional.
            bcc: BCC recipient(s). Single string or list of strings. Optional.

        Returns:
            Dict with send result including provider used and message ID,
            or error dict with "error" and optional "help" keys.
        """
        return client.send_email(to, subject, html, from_email, provider, cc, bcc)

    @mcp.tool()
    def send_budget_alert_email(
        to: str | list[str],
        budget_name: str,
        current_spend: float,
        budget_limit: float,
        currency: str = "USD",
        from_email: str | None = None,
        provider: Literal["auto", "resend", "gmail"] = "auto",
        cc: str | list[str] | None = None,
        bcc: str | list[str] | None = None,
    ) -> dict:
        """
        Send a budget alert email notification.

        Generates a formatted HTML email for budget threshold alerts
        and sends it via the configured email provider.

        Args:
            to: Recipient email address(es).
            budget_name: Name of the budget (e.g., "Marketing Q1").
            current_spend: Current spending amount.
            budget_limit: Budget limit amount.
            currency: Currency code (default: "USD").
            from_email: Sender email address. Falls back to EMAIL_FROM env var if not provided.
                        Optional for Gmail (defaults to authenticated user's address).
            provider: Email provider to use ("auto", "gmail", or "resend").
            cc: CC recipient(s). Single string or list of strings. Optional.
            bcc: BCC recipient(s). Single string or list of strings. Optional.

        Returns:
            Dict with send result or error dict.
        """
        percentage = (current_spend / budget_limit * 100) if budget_limit > 0 else 0

        if percentage >= 100:
            severity = "EXCEEDED"
            color = "#dc2626"
        elif percentage >= 90:
            severity = "CRITICAL"
            color = "#ea580c"
        elif percentage >= 75:
            severity = "WARNING"
            color = "#ca8a04"
        else:
            severity = "INFO"
            color = "#2563eb"

        subject = f"[{severity}] Budget Alert: {budget_name} at {percentage:.0f}%"
        html = f"""
        <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
            <h2 style="color: {color};">Budget Alert: {severity}</h2>
            <p><strong>Budget:</strong> {budget_name}</p>
            <p><strong>Current Spend:</strong> {currency} {current_spend:,.2f}</p>
            <p><strong>Budget Limit:</strong> {currency} {budget_limit:,.2f}</p>
            <p><strong>Usage:</strong>
                <span style="color: {color}; font-weight: bold;">{percentage:.1f}%</span></p>
        </div>
        """

        return client.send_email(
            to=to,
            subject=subject,
            html=html,
            from_email=from_email,
            provider=provider,
            cc=cc,
            bcc=bcc,
        )
