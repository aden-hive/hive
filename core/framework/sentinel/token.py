"""Correlation tokens for Sentinel escalations.

An escalation sent to a messaging channel carries a short, opaque
``(ref: …)`` footer. When the user replies, the token routes the reply
back to the exact escalation (and thus the colony/session it belongs to).

The token is an HMAC of the ``escalation_id`` under a per-install secret,
so it is:

  * **opaque** — it leaks neither the colony nor the session id;
  * **unforgeable** — a stranger in a shared Slack channel cannot mint a
    token for someone else's escalation without the secret;
  * **deterministic** — recomputable from the ``escalation_id``, so the
    inbound side verifies by recompute + constant-time compare rather than
    by trusting the wire value.

The secret lives at ``$HIVE_HOME/sentinel_secret`` (0600), created lazily
on first use.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import secrets

from framework.config import HIVE_HOME

logger = logging.getLogger(__name__)

_SECRET_PATH = HIVE_HOME / "sentinel_secret"
# base32 alphabet is A-Z2-7; we lowercase the token, so match a-z2-7.
_REF_RE = re.compile(r"ref:\s*([a-z2-7]{6,32})", re.IGNORECASE)
_TOKEN_LEN = 16

_cached_secret: bytes | None = None


def _load_or_create_secret() -> bytes:
    """Return the per-install HMAC secret, creating it (0600) if absent."""
    global _cached_secret
    if _cached_secret is not None:
        return _cached_secret
    try:
        if _SECRET_PATH.exists():
            data = _SECRET_PATH.read_bytes().strip()
            if data:
                _cached_secret = base64.b64decode(data)
                return _cached_secret
    except (OSError, ValueError):
        logger.warning("sentinel: could not read secret, regenerating", exc_info=True)

    secret = secrets.token_bytes(32)
    try:
        _SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(_SECRET_PATH), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(base64.b64encode(secret))
    except OSError:
        # In-memory only this run — tokens still work until restart.
        logger.warning("sentinel: could not persist secret; using ephemeral", exc_info=True)
    _cached_secret = secret
    return secret


def make_token(escalation_id: str) -> str:
    """Deterministic opaque token for an escalation id."""
    mac = hmac.new(_load_or_create_secret(), escalation_id.encode(), hashlib.sha256).digest()
    return base64.b32encode(mac).decode().rstrip("=").lower()[:_TOKEN_LEN]


def verify_token(token: str | None, escalation_id: str) -> bool:
    """Constant-time check that ``token`` matches ``escalation_id``."""
    if not token:
        return False
    return hmac.compare_digest(token.lower(), make_token(escalation_id))


def extract_token(text: str | None) -> str | None:
    """Pull a ``(ref: …)`` token out of a free-text reply, or None."""
    if not text:
        return None
    m = _REF_RE.search(text)
    return m.group(1).lower() if m else None


def format_ref(token: str) -> str:
    """Render the footer appended to an outbound escalation message."""
    return f"(ref: {token})"


def strip_ref(text: str | None) -> str:
    """Remove the ``(ref: …)`` footer from a reply so it isn't fed to the queen."""
    if not text:
        return ""
    return re.sub(r"\(?\s*ref:\s*[a-z2-7]{6,32}\s*\)?", "", text, flags=re.IGNORECASE).strip()


def _reset_secret_cache_for_tests() -> None:
    """Drop the cached secret so a test can repoint ``HIVE_HOME``."""
    global _cached_secret
    _cached_secret = None
