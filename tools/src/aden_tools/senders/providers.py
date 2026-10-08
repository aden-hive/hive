"""Per-provider single-email send.

One function per provider, plus :func:`send_one` which dispatches on a
resolved :class:`SenderConfig`. Every function returns a normalized dict:
``{"success": True, "provider": ..., "id": ...}`` or ``{"error": ...}``.

Provider asymmetry to be aware of (surfaced, not hidden):
- google/mailjet/sendgrid/smtp take raw subject + html, plus an optional plain
  ``text`` alternative (the two are the same message, not two messages).
- hubspot sends a *pre-built marketing email* via the Marketing Single-Send
  API, which is keyed by an ``emailId`` (a marketing email designed in
  HubSpot), NOT raw html. For HubSpot senders you must pass
  ``hubspot_email_id``; subject/html are ignored.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from .registry import SenderConfig, SenderRegistry

_TIMEOUT = 30.0


def _mime_raw(to: str, subject: str, html: str, from_header: str, text: str = "") -> str:
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart("alternative")
    msg["To"] = to
    msg["Subject"] = subject
    msg["From"] = from_header
    # multipart/alternative is ordered worst-to-best: the client picks the LAST
    # part it can render. Plain text must be attached before the html, or a
    # client that understands both shows the plain version.
    if text:
        msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def _from_header(from_email: str, from_name: str | None) -> str:
    return f"{from_name} <{from_email}>" if from_name else from_email


def send_via_gmail(
    access_token: str,
    from_email: str,
    from_name: str | None,
    to_email: str,
    subject: str,
    html: str,
    text: str = "",
) -> dict[str, Any]:
    raw = _mime_raw(to_email, subject, html, _from_header(from_email, from_name), text)
    resp = httpx.post(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={"raw": raw},
        timeout=_TIMEOUT,
    )
    if resp.status_code == 401:
        return {"error": "Gmail token expired or invalid; reconnect the Google sender"}
    if resp.status_code != 200:
        return {"error": f"Gmail API error (HTTP {resp.status_code}): {resp.text}"}
    return {"success": True, "provider": "google", "id": resp.json().get("id", "")}


def send_via_sendgrid(
    api_key: str,
    from_email: str,
    from_name: str | None,
    to_email: str,
    subject: str,
    html: str,
    text: str = "",
) -> dict[str, Any]:
    # SendGrid requires content[] ordered by increasing preference — text/plain
    # must precede text/html or the API rejects the payload outright.
    content: list[dict[str, str]] = []
    if text:
        content.append({"type": "text/plain", "value": text})
    content.append({"type": "text/html", "value": html})
    body: dict[str, Any] = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": from_email, **({"name": from_name} if from_name else {})},
        "subject": subject,
        "content": content,
    }
    resp = httpx.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=_TIMEOUT,
    )
    if resp.status_code in (200, 202):
        # SendGrid returns the message id in the X-Message-Id header.
        return {"success": True, "provider": "sendgrid", "id": resp.headers.get("X-Message-Id", "")}
    if resp.status_code == 401:
        return {"error": "SendGrid rejected the API key"}
    return {"error": f"SendGrid API error (HTTP {resp.status_code}): {resp.text}"}


def send_via_mailjet(
    api_key: str,
    secret_key: str,
    from_email: str,
    from_name: str | None,
    to_email: str,
    subject: str,
    html: str,
    text: str = "",
) -> dict[str, Any]:
    message: dict[str, Any] = {
        "From": {"Email": from_email, **({"Name": from_name} if from_name else {})},
        "To": [{"Email": to_email}],
        "Subject": subject,
        "HTMLPart": html,
    }
    if text:
        message["TextPart"] = text
    body = {"Messages": [message]}
    resp = httpx.post(
        "https://api.mailjet.com/v3.1/send",
        auth=(api_key, secret_key),
        json=body,
        timeout=_TIMEOUT,
    )
    if resp.status_code in (200, 201):
        data = resp.json()
        msgs = data.get("Messages", [])
        msg_id = ""
        if msgs and msgs[0].get("To"):
            msg_id = str(msgs[0]["To"][0].get("MessageID", ""))
        status = msgs[0].get("Status") if msgs else None
        if status and status != "success":
            return {"error": f"Mailjet did not accept the message: {data}"}
        return {"success": True, "provider": "mailjet", "id": msg_id}
    if resp.status_code == 401:
        return {"error": "Mailjet rejected the API key/secret"}
    return {"error": f"Mailjet API error (HTTP {resp.status_code}): {resp.text}"}


def send_via_hubspot_marketing(
    access_token: str,
    email_id: int,
    to_email: str,
    custom_properties: dict[str, Any] | None = None,
    contact_properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send a pre-built HubSpot marketing email via the Single-Send API.

    Uses POST /marketing/v3/email/single-send with an ``emailId`` referencing
    a marketing email designed in HubSpot. Requires the OAuth scope granted
    to marketing single-send.
    """
    message: dict[str, Any] = {"to": to_email}
    body: dict[str, Any] = {"emailId": email_id, "message": message}
    if contact_properties:
        body["contactProperties"] = contact_properties
    if custom_properties:
        body["customProperties"] = custom_properties
    resp = httpx.post(
        "https://api.hubapi.com/marketing/v3/email/single-send",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json=body,
        timeout=_TIMEOUT,
    )
    if resp.status_code in (200, 201):
        data = resp.json()
        return {"success": True, "provider": "hubspot", "id": str(data.get("requestedAt", ""))}
    if resp.status_code == 401:
        return {"error": "HubSpot token expired or invalid; reconnect the HubSpot sender"}
    if resp.status_code == 403:
        return {"error": "HubSpot rejected the request (missing marketing single-send scope?)"}
    return {"error": f"HubSpot API error (HTTP {resp.status_code}): {resp.text}"}


def send_via_smtp(
    secret: dict[str, Any],
    from_email: str,
    from_name: str | None,
    to_email: str,
    subject: str,
    html: str,
    text: str = "",
    *,
    message_id: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> dict[str, Any]:
    """Send through a real mailbox over SMTP.

    Unlike the ESP providers, this is a *mailbox*: the message lands in the
    account's Sent folder and a reply comes back to its inbox, which is what
    makes a two-way conversation possible at all.

    ``message_id`` is the RFC 5322 Message-ID to stamp on the mail. We mint it
    ourselves (rather than letting the server assign one) because the reply's
    ``In-Reply-To`` echoes it back verbatim — that is the correlation handle the
    reply poller uses to find the conversation this reply belongs to.
    """
    import smtplib
    import ssl
    from email.message import EmailMessage

    host = secret.get("host")
    port = int(secret.get("port") or 587)
    username = secret.get("username")
    password = secret.get("password")
    security = (secret.get("security") or "starttls").lower()
    if not host or not username or not password:
        return {"error": "SMTP sender is missing host/username/password"}

    msg = EmailMessage()
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["From"] = _from_header(from_email, from_name)
    if message_id:
        msg["Message-ID"] = message_id
    # Threading headers: set on a reply so the recipient's client (and ours)
    # files it into the existing conversation instead of starting a new one.
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references
    # set_content() is the text/plain part — what a text-only client, and many
    # spam filters, actually read. Until we threaded `text` through, this was a
    # hardcoded apology, so every SMTP send shipped a junk plain-text body.
    msg.set_content(text or "This message requires an HTML-capable email client.")
    msg.add_alternative(html, subtype="html")

    try:
        ctx = ssl.create_default_context()
        if security == "tls" or port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=_TIMEOUT, context=ctx) as s:
                s.login(username, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=_TIMEOUT) as s:
                s.ehlo()
                if security != "none":
                    s.starttls(context=ctx)
                    s.ehlo()
                s.login(username, password)
                s.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        # By far the most common cause on Gmail/Workspace: an account password
        # was used where a 16-char App Password is required.
        return {"error": f"{host} rejected the login for {username} ({e.smtp_code}). {e.smtp_error!r}"}
    except smtplib.SMTPRecipientsRefused:
        return {"error": f"{host} refused the recipient {to_email}"}
    except smtplib.SMTPException as e:
        return {"error": f"SMTP error from {host}: {e}"}
    except OSError as e:
        return {"error": f"Could not reach {host}:{port} — {e}"}

    # SMTP has no server-side id to return; the Message-ID we minted IS the
    # handle, and it's what a reply will quote back at us.
    return {"success": True, "provider": "smtp", "id": message_id or ""}


def send_one(
    registry: SenderRegistry,
    sender: SenderConfig,
    to_email: str,
    subject: str,
    html: str,
    text: str = "",
    *,
    hubspot_email_id: int | None = None,
    custom_properties: dict[str, Any] | None = None,
    message_id: str | None = None,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> dict[str, Any]:
    """Dispatch one send to the sender's provider. Returns a normalized dict.

    ``html`` and ``text`` are the two alternatives of one message; ``text`` is
    optional but should almost always be set (the tool layer derives it), since
    text-only clients and spam filters read it.
    """
    try:
        if sender.provider == "smtp":
            return send_via_smtp(
                sender.secret or {},
                sender.from_email,
                sender.from_name,
                to_email,
                subject,
                html,
                text,
                message_id=message_id,
                in_reply_to=in_reply_to,
                references=references,
            )

        if sender.provider == "google":
            token = registry.resolve_oauth_token(sender)
            if not token:
                return {"error": f"Could not resolve Google token for sender '{sender.name}'"}
            return send_via_gmail(token, sender.from_email, sender.from_name, to_email, subject, html, text)

        if sender.provider == "sendgrid":
            secret = sender.secret or {}
            if not secret.get("api_key"):
                return {"error": f"SendGrid sender '{sender.name}' has no api_key"}
            return send_via_sendgrid(secret["api_key"], sender.from_email, sender.from_name, to_email, subject, html, text)

        if sender.provider == "mailjet":
            secret = sender.secret or {}
            if not secret.get("api_key") or not secret.get("secret_key"):
                return {"error": f"Mailjet sender '{sender.name}' is missing api_key/secret_key"}
            return send_via_mailjet(
                secret["api_key"],
                secret["secret_key"],
                sender.from_email,
                sender.from_name,
                to_email,
                subject,
                html,
                text,
            )

        if sender.provider == "hubspot":
            if hubspot_email_id is None:
                return {
                    "error": (
                        f"HubSpot sender '{sender.name}' needs hubspot_email_id "
                        "(the id of a marketing email built in HubSpot); subject/html are ignored."
                    )
                }
            token = registry.resolve_oauth_token(sender)
            if not token:
                return {"error": f"Could not resolve HubSpot token for sender '{sender.name}'"}
            return send_via_hubspot_marketing(token, hubspot_email_id, to_email, custom_properties=custom_properties)

        return {"error": f"Unsupported sender provider: {sender.provider}"}
    except httpx.TimeoutException:
        return {"error": "Request timed out"}
    except httpx.RequestError as e:
        return {"error": f"Network error: {e}"}
