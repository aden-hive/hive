"""The send log — reserve a slot in the cloud, send, then report the outcome.

This replaces ``rotation.py``'s local usage counter as the enforcement point
for ``daily_limit``. The counter could never be right:

  * it lived in one JSON file on one laptop, while the sender pool is
    team-scoped — two teammates sending from the same sender each kept a
    private count, so a "40/day" cap sent 80;
  * it was incremented read-modify-write with no lock, so concurrent workers
    lost increments and overshot the cap;
  * it was a COUNT, not a RECORD: it could not say what was sent or to whom,
    so a campaign could not be audited after the fact.

The cloud counts rows in an append-only log instead, inside a transaction
holding a per-sender lock, and hands back a slot the device has already paid
for. See hive-backend migrations/042_team_sender_sends.sql.

Failure policy — deliberate, and asymmetric:

    A sender WITH a daily_limit whose reservation cannot be made (cloud
    unreachable) does NOT send. A sender with no limit does.

Because the errors are not symmetric. Over-sending from a cold outbound domain
burns the domain, and no retry undoes it. Failing to send is an inconvenience
you can fix by trying again. When we cannot tell how much budget is left, the
safe assumption is "none".
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from .registry import get_registry

log = logging.getLogger(__name__)


def _cloud() -> Any | None:
    return get_registry().cloud()


def default_idempotency_key(colony_id: str, to_email: str, subject: str, campaign_id: str = "", step: int = 1) -> str:
    """A stable key for "this logical message to this person".

    Retrying a send after a network blip must NOT deliver a second copy. The key
    is derived from what makes a message unique to a recipient — so a retry with
    the same content resolves to the same reservation, while a genuinely new
    message (different subject, next step in a sequence) gets a new one.

    Deliberately NOT random: a random key would make every retry look new, which
    is precisely the bug this prevents.
    """
    raw = "|".join([colony_id, campaign_id, to_email.strip().lower(), subject.strip(), str(step)])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def reserve(
    *,
    sender_id: str,
    to_email: str,
    subject: str = "",
    colony_id: str = "",
    conversation_token: str | None = None,
    message_id: str | None = None,
    campaign_id: str = "",
    step: int = 1,
    idempotency_key: str = "",
) -> dict[str, Any]:
    """Claim a slot against the sender's daily budget. See module docstring.

    Returns the cloud's verdict: ``{"allowed": bool, "send_id": str|None,
    "sent_today": int, "daily_limit": int|None, "remaining_today": int|None,
    "reason"?: str}``. ``allowed=False`` means do not send.
    """
    client = _cloud()
    sender = get_registry().get(sender_id)
    has_limit = sender is not None and sender.daily_limit is not None

    if client is None:
        # No cloud (signed out / no API key). Enforce the asymmetry: a capped
        # sender must not send when the cap cannot be checked.
        if has_limit:
            return {
                "allowed": False,
                "send_id": None,
                "reason": (
                    "Cannot reach Aden cloud to check this sender's daily limit, and it "
                    "has one. Refusing to send rather than risk exceeding it — a "
                    "burned sending domain can't be undone. Sign in and retry."
                ),
            }
        return {"allowed": True, "send_id": None, "daily_limit": None}

    payload: dict[str, Any] = {"sender_id": sender_id, "to_email": to_email}
    if subject:
        payload["subject"] = subject[:998]
    if colony_id:
        payload["colony_id"] = colony_id
    if conversation_token:
        payload["conversation_token"] = conversation_token
    if message_id:
        payload["message_id"] = message_id
    if campaign_id:
        payload["campaign_id"] = campaign_id
    if step != 1:
        payload["step"] = step
    # Always send a key. Retry safety must not be opt-in — the caller who forgets
    # it is exactly the caller who will double-send.
    payload["idempotency_key"] = idempotency_key or default_idempotency_key(colony_id, to_email, subject, campaign_id, step)

    try:
        return client.reserve_send(payload)
    except Exception as e:
        log.warning("Send log: reservation failed for %s: %s", sender_id, e)
        if has_limit:
            return {
                "allowed": False,
                "send_id": None,
                "reason": (
                    f"Could not reserve a send slot with Aden cloud ({e}). This sender has a "
                    f"daily limit, so the send was refused rather than risk exceeding it."
                ),
            }
        # No cap to break. Send, but the log will have a hole — say so upstream.
        return {"allowed": True, "send_id": None, "daily_limit": None, "unlogged": True}


def complete(send_id: str, *, status: str, provider_message_id: str = "", error: str = "") -> None:
    """Report the provider's verdict on a reserved send.

    Best-effort: if this call is lost, the reservation stays 'reserved' and
    keeps consuming budget. That is the intended failure mode — an unconfirmed
    send is assumed to have gone out.
    """
    if not send_id:
        return
    client = _cloud()
    if client is None:
        return
    outcome: dict[str, Any] = {"status": status}
    if provider_message_id:
        outcome["provider_message_id"] = provider_message_id[:998]
    if error:
        outcome["error"] = error[:2000]
    try:
        client.complete_send(send_id, outcome)
    except Exception as e:
        log.warning("Send log: could not complete %s: %s", send_id, e)


def usage_today() -> dict[str, int]:
    """Team-wide sends today, per sender id, derived from the cloud log.

    Empty when the cloud is unreachable. Callers that ENFORCE must not read an
    empty dict as "nothing sent" — reserve() is the enforcement point, and it
    fails closed. This is for display and for rotation preference only.
    """
    client = _cloud()
    if client is None:
        return {}
    try:
        raw = client.sender_usage_today()
    except Exception as e:
        log.warning("Send log: could not read usage: %s", e)
        return {}
    return {sid: int((row or {}).get("sent_today", 0)) for sid, row in raw.items()}


def suppress(email: str, reason: str, note: str = "") -> dict[str, Any]:
    """Add an address to the team's do-not-contact list."""
    client = _cloud()
    if client is None:
        return {"error": "Not signed in to Aden cloud."}
    try:
        return client.suppress_recipient(email, reason, note)
    except Exception as e:
        return {"error": str(e)}


def suppressions() -> list[dict[str, Any]]:
    """The do-not-contact list."""
    client = _cloud()
    if client is None:
        return []
    try:
        return client.list_suppressions()
    except Exception as e:
        log.warning("Send log: could not read suppressions: %s", e)
        return []


def history(**filters: Any) -> list[dict[str, Any]]:
    """The audit trail (newest first). Filters: sender_id, to_email, colony_id, limit."""
    client = _cloud()
    if client is None:
        return []
    try:
        return client.list_sends(**filters)
    except Exception as e:
        log.warning("Send log: could not read history: %s", e)
        return []
