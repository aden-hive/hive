"""Agent-driven sender setup: save what can be saved, hand off the rest.

The agent is often handed a pasted config blob (an outreach script's sender
table, a spreadsheet row) mixing things it CAN finish end-to-end with things
it cannot:

- ``sendgrid`` / ``mailjet`` — an API key is the whole credential. The agent
  creates the sender itself and the cloud live-checks the key.
- ``google`` / ``hubspot`` — OAuth. If the account is ALREADY connected the
  agent binds the sender to that integration; if not, only a human can walk
  the consent screen.
- anything else (SMTP + app password, an unknown host) — not modelled by the
  sender pool at all.

For the two cases the agent cannot finish, this module builds a ``hive://``
deep link carrying the fields it already knows, so the desktop app can open
the Add-Sender form pre-filled and the user only supplies the auth. Failing
to save is therefore never a dead end — it degrades into a one-click handoff.

Deliverability caveat (why this module exists rather than a thin wrapper):
the cloud's ``validate`` only proves the CREDENTIAL works. It does not prove
``from_email`` is allowed to send. A SendGrid key is valid for the whole
account, so a sender can validate green and still bounce every message if the
from-address was never verified / its domain never authenticated. We therefore
cross-check the from-address against the provider's verified list and report
``from_verified`` honestly instead of implying a working sender.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

from .registry import get_registry

log = logging.getLogger(__name__)

# Providers the sender pool models, and how each is authenticated.
_AUTH_TYPE_BY_PROVIDER: dict[str, str] = {
    "google": "oauth",
    "hubspot": "oauth",
    "mailjet": "api_key",
    "sendgrid": "api_key",
    "smtp": "api_key",  # owns its secret; the secret is a login, not a key
}

# What a pasted config might call a provider.
#
# The two ESP hosts map to that ESP's HTTP API rather than to generic SMTP: the
# same SendGrid key authenticates both smtp.sendgrid.net and the v3 API we
# actually send on, and the API gives better errors. Anything else that looks
# like a mail host is a real mailbox -> the `smtp` provider.
_PROVIDER_ALIASES: dict[str, str] = {
    "google": "google",
    "gmail": "google",
    "hubspot": "hubspot",
    "sendgrid": "sendgrid",
    "smtp.sendgrid.net": "sendgrid",
    "mailjet": "mailjet",
    "in-v3.mailjet.com": "mailjet",
    "smtp": "smtp",
    "imap": "smtp",
    "mailbox": "smtp",
}

# Well-known IMAP host for a given SMTP host, so a user who pastes only SMTP
# details still gets a *receiving* mailbox (and therefore a reply loop) instead
# of a silently send-only one.
_IMAP_HOST_BY_SMTP: dict[str, str] = {
    "smtp.gmail.com": "imap.gmail.com",
    "smtp.office365.com": "outlook.office365.com",
    "smtp.mail.yahoo.com": "imap.mail.yahoo.com",
    "smtp.zoho.com": "imap.zoho.com",
    "smtp.fastmail.com": "imap.fastmail.com",
}


def normalize_provider(provider: str) -> str | None:
    """Map a pasted provider/smtp_host to a modelled provider, or None.

    An unrecognized *hostname* is treated as a generic mailbox rather than an
    unknown provider — that is the whole point of the smtp provider, and it is
    what lets a pasted config with an arbitrary mail host configure itself.
    """
    key = (provider or "").strip().lower()
    if key in _PROVIDER_ALIASES:
        return _PROVIDER_ALIASES[key]
    # Looks like a mail host (has a dot, no spaces) -> generic mailbox.
    if "." in key and " " not in key and "@" not in key:
        return "smtp"
    return None


def default_imap_host(smtp_host: str) -> str | None:
    """The IMAP host that pairs with this SMTP host, if we know it."""
    host = (smtp_host or "").strip().lower()
    if host in _IMAP_HOST_BY_SMTP:
        return _IMAP_HOST_BY_SMTP[host]
    # Convention that holds across most providers (smtp.x.com -> imap.x.com).
    if host.startswith("smtp."):
        return "imap." + host[len("smtp.") :]
    return None


def auth_type(provider: str) -> str:
    return _AUTH_TYPE_BY_PROVIDER.get(provider, "")


def handoff_url(
    *,
    provider: str = "",
    from_email: str = "",
    name: str = "",
    from_name: str = "",
    reason: str = "",
) -> str:
    """A deep link that opens the desktop Add-Sender form, pre-filled.

    Consumed by the chat markdown renderer, which navigates in-app rather than
    opening a browser. Only non-empty fields are carried so the form falls back
    to its own defaults.
    """
    params = {
        k: v
        for k, v in (
            ("provider", provider),
            ("from_email", from_email),
            ("name", name),
            ("from_name", from_name),
            ("reason", reason),
        )
        if v
    }
    return "hive://senders/add" + (f"?{urlencode(params)}" if params else "")


def _find_oauth_integration(provider: str, from_email: str) -> str | None:
    """An already-connected integration for this address, if one exists."""
    client = get_registry().cloud()
    if client is None:
        return None
    try:
        integrations = client.list_integrations()
    except Exception as e:
        log.warning("Sender setup: could not list integrations: %s", e)
        return None
    wanted = (from_email or "").strip().lower()
    for i in integrations:
        if i.provider == provider and i.status == "active" and (i.email or "").strip().lower() == wanted:
            return i.integration_id
    return None


def _check_from_verified(provider: str, secret: dict[str, Any], from_email: str) -> bool | None:
    """Is from_email verified at the provider? None when the check is unavailable.

    A False here does NOT mean the sender is unusable: SendGrid's verified-sender
    list covers single-sender verifications only, so an address on a fully
    domain-authenticated domain legitimately reports False.
    """
    client = get_registry().cloud()
    if client is None:
        return None
    try:
        verified = client.list_provider_verified_senders(provider, secret)
    except Exception as e:
        log.warning("Sender setup: verified-sender probe failed: %s", e)
        return None
    wanted = (from_email or "").strip().lower()
    return any((v.get("email") or "").strip().lower() == wanted for v in verified)


def setup_sender(
    *,
    provider: str,
    from_email: str,
    name: str = "",
    from_name: str = "",
    api_key: str = "",
    secret_key: str = "",
    integration_id: str = "",
    smtp_host: str = "",
    smtp_port: int = 0,
    username: str = "",
    password: str = "",
    imap_host: str = "",
    imap_port: int = 0,
    weight: int = 1,
    daily_limit: int | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Create one sender if the agent has everything it needs; else hand off.

    Returns a dict whose ``status`` is one of:

    - ``saved``       — the sender exists and its credential live-checked.
    - ``needs_user``  — the agent cannot finish; ``setup_url`` opens the
                        pre-filled form for the human to supply auth.
    - ``error``       — the input was self-contradictory (bad email, etc.).
    """
    display_name = (name or from_name or from_email or "").strip()
    resolved = normalize_provider(provider)

    if not from_email or "@" not in from_email:
        return {"status": "error", "error": f"Invalid from_email: {from_email!r}"}

    # Not a modelled provider (SMTP + app password, unknown host). The pool
    # cannot represent it at all — the closest real option is connecting the
    # mailbox over OAuth, so send them to the form with the address pre-filled.
    if resolved is None:
        return {
            "status": "needs_user",
            "provider": provider,
            "from_email": from_email,
            "reason": (
                f"'{provider}' is not a supported sender provider. Senders must be "
                "Gmail or HubSpot (connected over OAuth), or SendGrid or Mailjet "
                "(API key). An SMTP host + app password cannot be stored. To use "
                "this mailbox, connect it as Gmail over OAuth."
            ),
            "setup_url": handoff_url(
                from_email=from_email,
                name=display_name,
                from_name=from_name,
                reason=f"{provider} is not supported — connect this mailbox over OAuth instead",
            ),
        }

    client = get_registry().cloud()
    if client is None:
        return {
            "status": "error",
            "error": "This device is not signed in to Aden cloud (no ADEN_API_KEY), so senders cannot be created.",
        }

    payload: dict[str, Any] = {
        "name": display_name,
        "provider": resolved,
        "from_email": from_email,
        "weight": weight,
    }
    if from_name:
        payload["from_name"] = from_name
    if daily_limit is not None:
        payload["daily_limit"] = daily_limit
    if tags:
        payload["tags"] = tags

    from_verified: bool | None = None

    if resolved == "smtp":
        # A real mailbox. The credential is a login, and — unlike every other
        # provider here — it can also RECEIVE, which is what makes a reply loop
        # possible. Default IMAP on so the mailbox isn't silently reply-blind.
        host = smtp_host or provider  # the pasted smtp_host doubles as the provider
        if not host or "." not in host:
            return {"status": "error", "error": "SMTP senders need an smtp_host (e.g. smtp.gmail.com)."}
        user = username or from_email
        if not password:
            return {
                "status": "needs_user",
                "provider": "smtp",
                "from_email": from_email,
                "reason": (
                    f"No password supplied for the mailbox {from_email} on {host}. "
                    "Most providers (Gmail/Workspace included) require an app password, "
                    "not the account password."
                ),
                "setup_url": handoff_url(
                    provider="smtp",
                    from_email=from_email,
                    name=display_name,
                    from_name=from_name,
                    reason=f"paste the app password for {from_email}",
                ),
            }
        # Prefer a supplied inbox host; otherwise guess, and SAY it was a guess.
        # The cloud demotes a sender to send-only when a guessed inbox doesn't
        # answer, but hard-fails one the user explicitly asked for — we must not
        # fail a working mailbox on account of our own heuristic.
        inbox = imap_host or default_imap_host(host) or ""
        secret = {
            "host": host,
            "port": smtp_port or 587,
            "username": user,
            "password": password,
            "security": "tls" if (smtp_port or 587) == 465 else "starttls",
        }
        if inbox:
            secret["imap_host"] = inbox
            secret["imap_port"] = imap_port or 993
            if not imap_host:
                secret["imap_inferred"] = True
        payload["secret"] = secret

    elif auth_type(resolved) == "api_key":
        if not api_key:
            return {
                "status": "needs_user",
                "provider": resolved,
                "from_email": from_email,
                "reason": f"No API key supplied for the {resolved} sender {from_email}.",
                "setup_url": handoff_url(
                    provider=resolved,
                    from_email=from_email,
                    name=display_name,
                    from_name=from_name,
                    reason=f"paste the {resolved} API key",
                ),
            }
        if resolved == "mailjet" and not secret_key:
            return {
                "status": "error",
                "error": "Mailjet needs both an api_key and a secret_key.",
            }
        secret: dict[str, Any] = {"api_key": api_key}
        if secret_key:
            secret["secret_key"] = secret_key
        payload["secret"] = secret
        from_verified = _check_from_verified(resolved, secret, from_email)
    else:
        # OAuth. Bind to an already-connected account when one matches; the
        # consent screen is the one thing an agent genuinely cannot walk.
        bound = integration_id or _find_oauth_integration(resolved, from_email)
        if not bound:
            return {
                "status": "needs_user",
                "provider": resolved,
                "from_email": from_email,
                "reason": (
                    f"{from_email} is not connected over OAuth yet. Connecting it "
                    "requires signing in through the provider's consent screen, "
                    "which only you can do."
                ),
                "setup_url": handoff_url(
                    provider=resolved,
                    from_email=from_email,
                    name=display_name,
                    from_name=from_name,
                    reason=f"connect {from_email} over OAuth",
                ),
            }
        payload["integration_id"] = bound

    try:
        created = client.create_team_sender(payload)
    except Exception as e:
        # A rejected create still leaves the user a path: open the form.
        return {
            "status": "error",
            "provider": resolved,
            "from_email": from_email,
            "error": str(e),
            "setup_url": handoff_url(
                provider=resolved,
                from_email=from_email,
                name=display_name,
                from_name=from_name,
                reason="creating this sender failed — check the details",
            ),
        }

    get_registry().refresh()  # usable in this same conversation

    validation = created.get("validation") or {}
    result: dict[str, Any] = {
        "status": "saved",
        "sender_id": created.get("id", ""),
        "name": created.get("name", display_name),
        "provider": resolved,
        "from_email": from_email,
        "credential_valid": bool(validation.get("valid")),
    }
    if not validation.get("valid") and validation.get("error"):
        result["credential_error"] = validation["error"]

    # Can this sender hold a conversation? Only a mailbox can, and only if IMAP
    # was configured — the agent needs to know, because a send-only sender means
    # any reply the prospect writes is lost.
    if resolved == "smtp":
        result["can_receive"] = bool(created.get("can_receive"))
        if not result["can_receive"]:
            result["warning"] = (
                f"{from_email} can send but has no IMAP inbox configured, so replies "
                f"to it will NOT be seen by the agent. Add imap_host to enable the "
                f"reply loop."
            )

    # Honest deliverability signal — see the module docstring.
    if from_verified is False:
        result["from_verified"] = False
        result["warning"] = (
            f"The {resolved} credential works, but {from_email} is not in this "
            f"account's verified-sender list. If its domain is authenticated in "
            f"{resolved} this is fine; otherwise sends from this address will be "
            f"rejected. Verify the address or authenticate the domain in "
            f"{resolved} before running a campaign."
        )
    elif from_verified is True:
        result["from_verified"] = True

    return result
