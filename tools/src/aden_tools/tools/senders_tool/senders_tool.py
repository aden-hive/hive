"""Email senders tool — the queen's single, easy interface to the team's
cloud-configured sender pool, with sender rotation.

Senders are configured by the team on the Aden cloud (Gmail, Mailjet,
SendGrid, HubSpot) and pulled to the device. This tool lets an agent:

- ``list_senders``      — see every sender it can send from (+ today's usage).
- ``setup_email_sender``— add a sender the user described, or hand off a
  pre-filled form link when only a human can finish the auth.
- ``send_from_sender``  — send one email from a named sender.
- ``pick_sender``       — choose the next sender under a rotation policy.
- ``send_campaign``     — send to many recipients, rotating senders automatically.

The tool is credential-less at the MCP layer: it reads secrets/tokens from
the sender registry (which pulls them from cloud), not from the per-tool
credential store — so it is registered as a verified tool and is available
to every queen. It self-describes an empty pool when no senders exist.
"""

from __future__ import annotations

import json
import re
from html import escape, unescape
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP

from aden_tools.senders import (
    get_registry,
    providers as _providers,
    rotation as _rotation,
    sendlog as _sendlog,
    setup as _setup,
    threads as _threads,
)

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter
    from aden_tools.senders import SenderConfig


def _split(value: str) -> list[str]:
    """Split a comma/newline/space separated string into non-empty items."""
    if not value:
        return []
    out: list[str] = []
    for chunk in value.replace("\n", ",").replace(" ", ",").split(","):
        item = chunk.strip()
        if item:
            out.append(item)
    return out


def _parse_recipients(recipients: str) -> list[str]:
    recipients = recipients.strip()
    if not recipients:
        return []
    if recipients.startswith("["):
        try:
            data = json.loads(recipients)
            if isinstance(data, list):
                return [str(x).strip() for x in data if str(x).strip()]
        except json.JSONDecodeError:
            pass
    return _split(recipients)


_HTML_TAG = re.compile(r"<(br|p|div|table|html|body|ul|ol|li|h[1-6]|span|strong|em|b|i|a|img)\b[^>]*>", re.I)


def _text_to_html(text: str) -> str:
    """Render a plain-text body as HTML.

    Providers send the html part as ``text/html``, and HTML collapses newlines
    into whitespace — so plain text passed straight through arrives as ONE
    JAMMED LINE (this shipped: 652 emails, 2026-07-13). Blank line = paragraph,
    single newline = <br>. Escape first, or a literal "R&D" or "<3" in the copy
    becomes broken markup.
    """
    paragraphs = re.split(r"\n\s*\n", text.strip())
    return "".join("<p>" + "<br>".join(escape(line) for line in p.split("\n")) + "</p>" for p in paragraphs if p.strip())


def _html_to_text(html: str) -> str:
    """Derive a readable plain-text alternative from an HTML body.

    Deliberately dumb — block tags become newlines, the rest are stripped. This
    is the part text-only clients and spam filters read, so an empty or
    tag-soup plain part is worse than a plain one.
    """
    out = re.sub(r"(?i)<br\s*/?>", "\n", html)
    out = re.sub(r"(?i)</(p|div|tr|li|h[1-6])\s*>", "\n\n", out)
    out = re.sub(r"(?i)<li\b[^>]*>", "• ", out)
    out = re.sub(r"(?i)<(script|style)\b.*?</\1>", "", out, flags=re.S)
    out = re.sub(r"<[^>]+>", "", out)
    out = unescape(out)
    out = re.sub(r"[ \t]+\n", "\n", out)
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def _resolve_body(html: str, text: str | None, legacy: str) -> tuple[str, str]:
    """Settle the (html, text) pair a send actually goes out with.

    The two fields are the two alternatives of ONE message, and the caller may
    legitimately supply either. Rules, matching how the ESPs document this:
      - html only        → text is generated from the html.
      - text only        → html is generated from the text (this is the common
                           agent case: bodies are stored as plain text).
      - both             → both used verbatim, no derivation.
      - text="" (explicit) → opt out; send html-only, no plain part.

    ``legacy`` is the deprecated ``html_content`` param. Old colonies pass plain
    text into it — that WAS the jamming bug — so sniff it rather than trusting
    its name, and route it to whichever field it actually turned out to be.
    """
    if legacy and not html and text is None:
        if _HTML_TAG.search(legacy):
            html = legacy
        else:
            text = legacy

    if not html and text:
        html = _text_to_html(text)
    elif html and text is None:
        text = _html_to_text(html)

    return html, text or ""


def _send_tracked(
    registry: Any,
    sender: SenderConfig,
    to_email: str,
    subject: str,
    html: str,
    colony_id: str,
    *,
    text: str = "",
    hubspot_email_id: int | None = None,
    campaign_id: str = "",
    step: int = 1,
) -> dict[str, Any]:
    """Send one mail and, when a reply could come back, remember the conversation.

    Only senders with an inbox get a tracked Message-ID: for a send-only ESP the
    reply lands somewhere we will never read, so minting a conversation token
    would promise a follow-up that can never happen.

    ``colony_id`` is injected by the framework (a CONTEXT_PARAM), not chosen by
    the model. Without it we cannot say which agent to wake on a reply, so the
    send still goes out — but untracked, and we say so.
    """
    trackable = bool(sender.can_receive and colony_id)

    message_id = ""
    token = ""
    if trackable:
        message_id, token = _threads.mint_message_id(sender.from_email)

    # RESERVE FIRST. The daily cap is enforced in the cloud, against the team's
    # send log, inside one transaction under a per-sender lock — because that is
    # the only vantage point that sees every teammate and every worker at once.
    # A local counter cannot: two laptops keep two private counts, so a cap of
    # 40 sends 80. Over-sending from a cold outbound domain is unrecoverable, so
    # this call gates the send rather than merely recording it.
    reservation = _sendlog.reserve(
        sender_id=sender.id,
        to_email=to_email,
        subject=subject,
        colony_id=colony_id,
        conversation_token=token or None,
        message_id=message_id or None,
        campaign_id=campaign_id,
        step=step,
    )
    if not reservation.get("allowed"):
        out: dict[str, Any] = {
            "error": reservation.get("reason", "This send was not permitted."),
            "sender": sender.name,
            "sent_today": reservation.get("sent_today"),
            "daily_limit": reservation.get("daily_limit"),
            "remaining_today": reservation.get("remaining_today", 0),
        }
        # Distinguish the refusals — an agent that reads "blocked" and retries a
        # DIFFERENT sender is right for a daily limit and very wrong for a
        # suppression or a duplicate.
        if reservation.get("duplicate"):
            out["duplicate"] = True
            out["guidance"] = "Already sent to this recipient. Do NOT retry or use another sender."
        elif reservation.get("denied_because") == "suppressed":
            out["suppressed"] = True
            out["guidance"] = "This person must not be contacted, by any sender. Remove them from the campaign; do not try again."
        elif reservation.get("denied_because") == "daily_limit":
            out["guidance"] = "This sender is exhausted for today. A different sender may still have budget."
        return out
    send_id = reservation.get("send_id") or ""

    result = _providers.send_one(
        registry,
        sender,
        to_email,
        subject,
        html,
        text,
        hubspot_email_id=hubspot_email_id,
        message_id=message_id or None,
    )

    # Close the loop either way. A failure releases the reserved slot, so a
    # provider rejection doesn't silently eat the domain's budget for the day.
    ok = bool(result.get("success"))
    _sendlog.complete(
        send_id,
        status="sent" if ok else "failed",
        provider_message_id=str(result.get("id") or "") if ok else "",
        error="" if ok else str(result.get("error", ""))[:2000],
    )
    if not ok:
        return result

    # Report the remaining budget after every send: the agent otherwise reasons
    # from a limit it saw earlier in the conversation, which is how a sender
    # capped at 4 gets described as "10 of its 100/day".
    if reservation.get("daily_limit") is not None:
        result["remaining_today"] = reservation.get("remaining_today")
        result["daily_limit"] = reservation.get("daily_limit")

    if trackable:
        _threads.record_send(
            token=token,
            message_id=message_id,
            colony_id=colony_id,
            sender_id=sender.id,
            from_email=sender.from_email,
            to_email=to_email,
            subject=subject,
        )
        result["conversation"] = token
    elif not sender.can_receive:
        result["reply_tracking"] = (
            f"none — '{sender.name}' has no inbox, so a reply from {to_email} will not reach you. Use a mailbox sender for conversations."
        )
    return result


def _candidate_pool(pool: str, tags: str) -> list[SenderConfig]:
    """Resolve the candidate senders from an optional id/name pool + tags."""
    registry = get_registry()
    senders = registry.list()  # enabled only
    wanted_ids = {p.lower() for p in _split(pool)}
    if wanted_ids:
        senders = [s for s in senders if s.id.lower() in wanted_ids or s.name.lower() in wanted_ids]
    wanted_tags = {t.lower() for t in _split(tags)}
    if wanted_tags:
        senders = [s for s in senders if wanted_tags & {t.lower() for t in s.tags}]
    return senders


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,  # noqa: ARG001 - registry-backed
) -> None:
    """Register the email-senders tools with the MCP server."""

    @mcp.tool()
    def list_senders() -> dict:
        """
        List the team's configured email senders this agent can send from.

        Returns each sender's id, name, provider, from address, tags, weight,
        daily_limit, plus how many emails it has already sent today and how
        many remain under its daily limit. Use these ids/names with
        send_from_sender, pick_sender, and send_campaign.
        """
        registry = get_registry()
        senders = registry.list(include_disabled=True)
        # Team-wide, from the cloud send log — the local counter only ever knew
        # about this device, so it under-reported whenever a teammate sent too.
        usage = _sendlog.usage_today()
        rows: list[dict[str, Any]] = []
        for s in senders:
            sent = int(usage.get(s.id, 0))
            remaining: int | None = None if s.daily_limit is None else max(0, s.daily_limit - sent)
            view = s.public_view()
            view["sent_today"] = sent
            view["remaining_today"] = remaining
            rows.append(view)
        return {"count": len(rows), "senders": rows}

    @mcp.tool()
    def send_from_sender(
        sender: str,
        to_email: str,
        subject: str = "",
        html: str = "",
        text: str | None = None,
        hubspot_email_id: int = 0,
        campaign_id: str = "",
        colony_id: str = "",
        html_content: str = "",
    ) -> dict:
        """
        Send a single email from a named team sender (one of the configured
        Gmail/Mailjet/SendGrid/HubSpot/mailbox senders — see list_senders).

        Args:
            sender: Sender id or name (from list_senders).
            to_email: Recipient email address.
            subject: Subject line (ignored for HubSpot senders).
            html: The HTML version of the message. If not provided, it is
                generated from `text` (newlines become real line breaks).
            text: The plain text version of the message. If not provided, it is
                generated from the HTML. Opt out by setting it to an empty
                string. Writing a plain-text body? Put it HERE, not in `html` —
                newlines in an HTML body collapse and the email arrives as one
                jammed line.
            hubspot_email_id: For HubSpot senders only — the id of a marketing
                email built in HubSpot to send via the Marketing Single-Send
                API. Required for HubSpot; ignored for other providers.
            html_content: Deprecated alias for `html`. Use `html`/`text`.

        Returns:
            {"success": True, "provider": ..., "id": ..., "conversation"?: ...}.
            When the sender has an inbox, `conversation` means the reply will be
            routed back to you; its absence means this send is a dead end.
        """
        registry = get_registry()
        resolved = registry.get(sender)
        if resolved is None:
            available = [s.name for s in registry.list()]
            return {"error": f"No sender named '{sender}'", "available_senders": available}
        if not to_email or "@" not in to_email:
            return {"error": "Invalid recipient email address"}

        body_html, body_text = _resolve_body(html, text, html_content)
        if resolved.provider != "hubspot":
            if not subject:
                return {"error": "subject cannot be empty"}
            if not body_html:
                return {"error": "Provide a body: `html`, or `text` for a plain-text message."}

        outcome = _send_tracked(
            registry,
            resolved,
            to_email,
            subject,
            body_html,
            colony_id,
            text=body_text,
            hubspot_email_id=hubspot_email_id or None,
            campaign_id=campaign_id,
        )
        if outcome.get("success"):
            outcome["sender"] = resolved.name
        return outcome

    @mcp.tool()
    def setup_email_sender(
        provider: str,
        from_email: str,
        name: str = "",
        from_name: str = "",
        api_key: str = "",
        secret_key: str = "",
        smtp_host: str = "",
        smtp_port: int = 0,
        username: str = "",
        password: str = "",
        imap_host: str = "",
        imap_port: int = 0,
        weight: int = 1,
        daily_limit: int = 0,
        tags: str = "",
    ) -> dict:
        """
        Add a new email sender to the team's pool, on the user's behalf.

        Call this once per sender when the user gives you sender details (e.g.
        pastes a config block with from-addresses, hosts and passwords). Save
        what you can; anything needing a human hands back a `setup_url`.

        Pick the provider by what the credential IS:
          - smtp: a MAILBOX — a mail host plus a username/password (often a
            16-char app password). This is the only sender that can also
            RECEIVE, so replies from prospects come back to the agent. Prefer
            it for cold outbound: ESPs forbid unsolicited mail and can't read
            replies. Pass smtp_host + password (username defaults to
            from_email); imap_host is inferred (smtp.x.com -> imap.x.com) so the
            reply loop works by default.
          - sendgrid / mailjet: an ESP API key. Send-only — a reply to one of
            these is never seen. Use for transactional mail, not conversations.
          - google (Gmail) / hubspot: OAuth. If that address is ALREADY
            connected the sender binds to it automatically; otherwise only the
            user can complete the consent screen.

        Args:
            provider: 'smtp', 'sendgrid', 'mailjet', 'google'/'gmail', or
                'hubspot'. A bare mail host from a pasted config also works —
                'smtp.gmail.com' means a mailbox, 'smtp.sendgrid.net' means the
                SendGrid API (the same key authenticates both).
            from_email: The address this sender sends from.
            name: Label for the sender (defaults to the from address).
            from_name: Display name on the outgoing email (e.g. 'Richard').
            api_key: SendGrid/Mailjet API key. Required for those providers.
            secret_key: Mailjet secret key (Mailjet only — it needs both).
            smtp_host: Mail host for an smtp sender (e.g. 'smtp.gmail.com').
            smtp_port: Defaults to 587 (STARTTLS); 465 selects implicit TLS.
            username: Mailbox login. Defaults to from_email.
            password: Mailbox password — usually an APP password, not the
                account password.
            imap_host: Inbox host. Inferred from smtp_host when omitted; pass
                it explicitly only if the guess is wrong. Without an inbox the
                sender is send-only and replies are lost.
            imap_port: Defaults to 993.
            weight: Rotation weight under the 'weighted' policy.
            daily_limit: Max sends/day for this sender; 0 = no limit. Cold
                outbound should cap each mailbox well below its provider limit.
            tags: Optional comma-separated tags.

        Returns one of:
            {"status": "saved", sender_id, credential_valid, can_receive?,
             from_verified?, warning?} — created. ALWAYS surface `warning`: a
                valid credential does NOT prove the from-address can send, nor
                that replies will be seen.
            {"status": "needs_user", reason, setup_url} — you cannot finish
                this one. Show the user `reason`, then the `setup_url` as a
                markdown link (e.g. "[Finish setting up richard@x.com](URL)")
                — it opens the pre-filled form in the app.
            {"status": "error", error} — bad input.
        """
        return _setup.setup_sender(
            provider=provider,
            from_email=from_email,
            name=name,
            from_name=from_name,
            api_key=api_key,
            secret_key=secret_key,
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            username=username,
            password=password,
            imap_host=imap_host,
            imap_port=imap_port,
            weight=weight,
            daily_limit=daily_limit or None,
            tags=_split(tags),
        )

    @mcp.tool()
    def adjust_sender(
        sender: str,
        daily_limit: int = -1,
        weight: int = -1,
        enabled: str = "",
        name: str = "",
        tags: str = "",
    ) -> dict:
        """
        Tune an existing sender: how much it sends, how often it's picked, its
        label. Use this to pace a campaign — e.g. warming a new domain by
        starting at 10/day, throttling a sender whose messages are bouncing, or
        pausing one entirely.

        You CANNOT change a sender's from-address or credential here. Those
        would break sends already in flight; direct the user to the Senders page
        for that.

        A note on daily_limit: it is the ceiling that protects the sending
        domain's reputation. Raising it increases real-world risk — a domain
        burned by over-sending cannot be un-burned. Lower it freely; raise it
        only when the user has asked for more volume, and say what you changed.

        Args:
            sender: Sender id or name (from list_senders).
            daily_limit: New cap (0 = block all sends). Omit to leave unchanged.
            weight: Rotation weight under the 'weighted' policy. Omit to leave
                unchanged. Relative, not absolute — it splits volume between
                senders; it does not raise the total.
            enabled: 'true' to resume, 'false' to pause. Omit to leave unchanged.
            name: New label. Omit to leave unchanged.
            tags: New comma-separated tags (replaces the existing ones).

        Returns:
            The updated sender, plus `changed` describing what actually moved.
        """
        registry = get_registry()
        resolved = registry.get(sender)
        if resolved is None:
            return {
                "error": f"No sender named '{sender}'",
                "available_senders": [s.name for s in registry.list()],
            }

        patch: dict[str, Any] = {}
        # -1 is the "not supplied" sentinel: 0 is a MEANINGFUL value for both
        # (a 0 daily_limit blocks sends; a 0 weight mutes a sender in rotation),
        # so it can't double as "unset".
        if daily_limit >= 0:
            patch["daily_limit"] = daily_limit
        if weight >= 0:
            patch["weight"] = weight
        if enabled:
            patch["enabled"] = enabled.strip().lower() in ("true", "yes", "1", "on")
        if name:
            patch["name"] = name
        if tags:
            patch["tags"] = _split(tags)
        if not patch:
            return {"error": "Nothing to change — supply at least one of daily_limit, weight, enabled, name, tags."}

        client = registry.cloud()
        if client is None:
            return {"error": "This device is not signed in to Aden cloud, so senders cannot be changed."}
        try:
            updated = client.update_team_sender(resolved.id, patch)
        except Exception as e:
            return {"error": str(e)}

        registry.refresh()  # the new limit must apply to the very next send

        changed = {k: {"from": getattr(resolved, k, None), "to": v} for k, v in patch.items() if getattr(resolved, k, None) != v}
        return {
            "sender": updated.get("name", resolved.name),
            "sender_id": resolved.id,
            "changed": changed,
            "daily_limit": updated.get("daily_limit"),
            "weight": updated.get("weight"),
            "enabled": updated.get("enabled"),
        }

    @mcp.tool()
    def suppress_recipient(email: str, reason: str = "unsubscribed", note: str = "") -> dict:
        """
        Add someone to the team's do-not-contact list. No sender may ever email
        them again — this is enforced at send time, so it cannot be bypassed.

        Call this IMMEDIATELY when a reply says any of: unsubscribe, remove me,
        stop, take me off your list, not interested — or when a person asks not
        to be contacted. Do not "finish the sequence first". Do not ask the user
        to confirm; honoring an opt-out is not optional, and a follow-up sent
        after one is both a legal problem and the fastest way to get a domain
        blacklisted.

        Args:
            email: The address to suppress.
            reason: 'unsubscribed' (they asked — the usual case), 'complained'
                (marked as spam), 'hard_bounce' (address is dead), or 'manual'
                (a human decision, e.g. an existing customer).
            note: Optional free text, e.g. the sentence they wrote.

        Returns:
            {"suppressed": email, "reason": ...} or {"error": ...}.
        """
        allowed = {"unsubscribed", "complained", "hard_bounce", "manual"}
        if reason not in allowed:
            reason = "manual"
        return _sendlog.suppress(email, reason, note)

    @mcp.tool()
    def list_suppressed() -> dict:
        """
        The do-not-contact list. Check it before building a recipient list —
        though a suppressed address is refused at send time regardless.
        """
        rows = _sendlog.suppressions()
        return {"count": len(rows), "suppressed": rows}

    @mcp.tool()
    def sender_history(
        sender: str = "",
        to_email: str = "",
        limit: int = 50,
        colony_id: str = "",
    ) -> dict:
        """
        The outbound send log — what was actually sent, to whom, and when.

        This is the team-wide record, not this device's. Use it to answer
        "have we emailed this person before?" before adding them to a campaign
        (contacting someone twice is worse than not contacting them), and to
        audit a campaign after the fact.

        Args:
            sender: Optional sender id or name to filter by.
            to_email: Optional recipient to filter by — the dedupe check.
            limit: Max rows (newest first). Default 50.

        Returns:
            {"count": N, "sends": [{to_email, subject, status, sent_at,
             sender_id, conversation_token}...]}. `status` is 'sent' (the
            provider accepted it), 'failed' (rejected), or 'reserved' (started,
            outcome unknown — assumed sent).
        """
        resolved = get_registry().get(sender) if sender else None
        rows = _sendlog.history(
            sender_id=resolved.id if resolved else "",
            to_email=to_email,
            colony_id=colony_id,
            limit=max(1, min(limit, 500)),
        )
        return {"count": len(rows), "sends": rows}

    @mcp.tool()
    def pick_sender(pool: str = "", policy: str = "round_robin", tags: str = "") -> dict:
        """
        Choose the next sender to use under a rotation policy, without sending.

        Args:
            pool: Optional comma-separated sender ids/names to choose among.
                Empty = all enabled senders.
            policy: 'round_robin' (default), 'weighted' (by each sender's
                weight), or 'least_used' (fewest sends today).
            tags: Optional comma-separated tags; restrict to senders carrying
                any of them.

        Returns:
            The chosen sender {id, name, provider, from_email} or an error if
            none are eligible (e.g. all hit their daily limit).
        """
        candidates = _candidate_pool(pool, tags)
        if not candidates:
            return {"error": "No senders match the requested pool/tags"}
        chosen = _rotation.pick(candidates, policy, usage=_sendlog.usage_today())
        if chosen is None:
            return {"error": "No eligible sender (all disabled or over daily limit)"}
        return {
            "id": chosen.id,
            "name": chosen.name,
            "provider": chosen.provider,
            "from_email": chosen.from_email,
        }

    @mcp.tool()
    def send_campaign(
        recipients: str,
        subject: str = "",
        html: str = "",
        text: str | None = None,
        policy: str = "round_robin",
        pool: str = "",
        tags: str = "",
        hubspot_email_id: int = 0,
        campaign_id: str = "",
        colony_id: str = "",
        html_content: str = "",
    ) -> dict:
        """
        Send an email to many recipients, rotating senders automatically.

        For each recipient a sender is chosen from the pool under `policy`
        (respecting per-sender daily limits), then the email is sent. This is
        the easy primitive for sender-rotated campaigns.

        Args:
            recipients: Recipient emails as a JSON array, or a comma/newline
                separated list.
            subject: Subject line (ignored for HubSpot senders).
            html: The HTML version of the message. If not provided, it is
                generated from `text` (newlines become real line breaks).
            text: The plain text version of the message. If not provided, it is
                generated from the HTML. Opt out by setting it to an empty
                string. Writing a plain-text body? Put it HERE, not in `html` —
                newlines in an HTML body collapse and the email arrives as one
                jammed line.
            policy: 'round_robin' (default), 'weighted', or 'least_used'.
            pool: Optional comma-separated sender ids/names to rotate among.
            tags: Optional comma-separated tags to restrict the pool.
            hubspot_email_id: Required when the pool contains HubSpot senders.
            html_content: Deprecated alias for `html`. Use `html`/`text`.

        Returns:
            {"sent": N, "failed": M, "tracked_for_replies": K, "warning"?: ...,
             "results": [{to, sender, success|error, conversation?}...]}.
            `tracked_for_replies` counts recipients whose reply will actually
            come back to you. If it is 0, every sender used was send-only.
        """
        to_list = _parse_recipients(recipients)
        if not to_list:
            return {"error": "No recipients provided"}
        candidates = _candidate_pool(pool, tags)
        if not candidates:
            return {"error": "No senders match the requested pool/tags"}

        # Resolve the body ONCE, not per recipient — the derivation is identical
        # for every send and a campaign can be thousands of rows.
        body_html, body_text = _resolve_body(html, text, html_content)
        if not body_html and not any(s.provider == "hubspot" for s in candidates):
            return {"error": "Provide a body: `html`, or `text` for a plain-text message."}

        registry = get_registry()
        # One read of team usage for the whole campaign; the cloud reservation
        # inside each send is what actually enforces the cap, so this only needs
        # to be good enough to STEER rotation away from exhausted senders.
        usage = _sendlog.usage_today()
        results: list[dict[str, Any]] = []
        sent = 0
        failed = 0
        for to_email in to_list:
            chosen = _rotation.pick(candidates, policy, usage=usage)
            if chosen is None:
                results.append({"to": to_email, "error": "No eligible sender (daily limits reached)"})
                failed += 1
                continue
            if not to_email or "@" not in to_email:
                results.append({"to": to_email, "sender": chosen.name, "error": "Invalid recipient"})
                failed += 1
                continue
            outcome = _send_tracked(
                registry,
                chosen,
                to_email,
                subject,
                body_html,
                colony_id,
                text=body_text,
                hubspot_email_id=hubspot_email_id or None,
                campaign_id=campaign_id,
            )
            if outcome.get("success"):
                row = {"to": to_email, "sender": chosen.name, "success": True, "id": outcome.get("id", "")}
                if outcome.get("conversation"):
                    row["conversation"] = outcome["conversation"]
                results.append(row)
                sent += 1
            else:
                results.append({"to": to_email, "sender": chosen.name, "error": outcome.get("error", "unknown")})
                failed += 1

        tracked = sum(1 for r in results if r.get("conversation"))
        out: dict[str, Any] = {
            "sent": sent,
            "failed": failed,
            "total": len(to_list),
            "tracked_for_replies": tracked,
            "results": results,
        }
        # Silence here would read as "replies are handled". Say it plainly.
        if sent and not tracked:
            out["warning"] = (
                "No recipient is tracked for replies — every sender used is send-only "
                "(an ESP with no inbox). Responses to this campaign will not reach you. "
                "Use a mailbox sender to hold a conversation."
            )
        return out
