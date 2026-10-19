"""Outbound conversation store — how a reply finds its way home.

The sender pool could always send. It could never *hear back*, because nothing
remembered that a message had been sent, so an inbound reply was just an
unrecognized email in a mailbox nobody read.

This is the missing half. Every outbound mail is stamped with an RFC 5322
``Message-ID`` we mint ourselves::

    Message-ID: <hive.7f3k9x2mqp4a@open-hive.com>
                      ^^^^^^^^^^^^ opaque conversation token

Per RFC 5322 a well-behaved mail client echoes that value back in the reply's
``In-Reply-To`` (and appends it to ``References``). So the reply carries the
token home for us — no plus-addressing, no visible "(ref: …)" footer of the kind
Sentinel needs on Slack/Telegram, nothing a prospect can see or strip by writing
a normal reply. We look the token up here and get back the colony that sent it,
which is what lets the poller wake the right agent.

Why a token rather than the raw ids: the Message-ID is public — it ships in the
headers of an email sent to a stranger. Embedding ``colony_id`` would leak the
internal structure of the user's workspace to every recipient. The token is
random and meaningless outside this store, and an inbound token we never minted
simply doesn't resolve, so a stranger cannot forge one to wake an agent.

State file: ``$HIVE_HOME/senders/threads.json`` (mirrors rotation.py's usage
store). Local by design — the device that sent is the device that polls.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# The token embedded in a Message-ID we minted. Base32-ish alphabet, lowercase.
_TOKEN_RE = re.compile(r"hive\.([a-z0-9]{8,32})@", re.IGNORECASE)
_TOKEN_BYTES = 8  # -> ~13 chars; unguessable, short enough to eyeball in logs


def _state_path() -> Path:
    base = os.environ.get("HIVE_HOME") or str(Path.home() / ".hive")
    return Path(base) / "senders" / "threads.json"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _load() -> dict[str, Any]:
    try:
        with _state_path().open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        pass
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Sender threads: unreadable store (%s); starting empty", e)
    return {}


def _save(state: dict[str, Any]) -> None:
    path = _state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: a crash mid-write must not truncate the store and
        # orphan every in-flight conversation.
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        log.warning("Sender threads: could not persist store: %s", e)


def _domain_of(email: str) -> str:
    return email.split("@", 1)[1] if "@" in email else "hive.local"


def mint_message_id(from_email: str) -> tuple[str, str]:
    """Return ``(message_id, token)`` for a new outbound conversation.

    The domain is the sender's own, so the Message-ID is well-formed for the
    sending host and doesn't look forged to a receiving spam filter.
    """
    token = secrets.token_hex(_TOKEN_BYTES)
    return f"<hive.{token}@{_domain_of(from_email)}>", token


def extract_token(*header_values: str | None) -> str | None:
    """Pull our token out of an inbound reply's threading headers.

    Pass ``In-Reply-To`` and ``References``. References accumulates the whole
    chain, so it still resolves on the 2nd/3rd reply of a long thread even when
    a client omits In-Reply-To.
    """
    for value in header_values:
        if not value:
            continue
        m = _TOKEN_RE.search(value)
        if m:
            return m.group(1).lower()
    return None


def record_send(
    *,
    token: str,
    message_id: str,
    colony_id: str,
    sender_id: str,
    from_email: str,
    to_email: str,
    subject: str,
) -> None:
    """Remember an outbound message so its reply can be routed back."""
    state = _load()
    state[token] = {
        "token": token,
        "message_id": message_id,
        "colony_id": colony_id,
        "sender_id": sender_id,
        "from_email": from_email,
        "to_email": to_email,
        "subject": subject,
        "sent_at": _now(),
        "replies": 0,
        "last_reply_at": None,
        # The chain we quote back when the agent replies, so the prospect's
        # client keeps the whole exchange in one thread.
        "references": [message_id],
    }
    _save(state)


def get(token: str) -> dict[str, Any] | None:
    return _load().get(token)


def record_reply(token: str) -> dict[str, Any] | None:
    """Mark that a reply arrived. Returns the (updated) conversation."""
    state = _load()
    rec = state.get(token)
    if rec is None:
        return None
    rec["replies"] = int(rec.get("replies", 0)) + 1
    rec["last_reply_at"] = _now()
    state[token] = rec
    _save(state)
    return rec


def all_conversations() -> list[dict[str, Any]]:
    return list(_load().values())
