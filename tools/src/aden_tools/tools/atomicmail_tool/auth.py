"""
Atomic Mail authentication: proof-of-work login and token lifecycle.

An Atomic Mail API key is not a bearer token. Using it takes three hops
against the auth service (https://docs.atomicmail.ai, rest-auth):

1. ``POST /api/v1/challenge`` returns a challenge JWT in the ``Authorization``
   response header. Its payload carries the PoW challenge (``jti``) and the
   number of leading zero bits required (``difficulty``).
2. ``POST /api/v1/session`` with the solved PoW and the API key returns a
   session JWT (valid ~1 hour).
3. ``POST /api/v1/capability`` with the session JWT returns a capability JWT
   (valid ~2 minutes). That token authorizes JMAP calls, and its ``inboxId``
   claim names the agent's mailbox.

:class:`AtomicMailSession` caches both tokens and refreshes them early, so a
PoW is solved roughly once an hour rather than on every tool call. The PoW
parameters mirror the reference client (atomic-mail-agentic, ``pow.py``).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
from typing import Any

import httpx

DEFAULT_AUTH_URL = "https://auth.atomicmail.ai"
DEFAULT_API_URL = "https://api.atomicmail.ai"
DEFAULT_SCRYPT_SALT = "0b980734412c292d6549110276b604ab1dea4883bd460d77d1b984adf8bca083"
DEFAULT_INBOX_DOMAIN = "atomicmail.ai"

# scrypt cost parameters used by the Atomic Mail auth service.
SCRYPT_N = 16_384
SCRYPT_R = 8
SCRYPT_P = 1
POW_HASH_BYTES = 64

# Treat tokens as expired this many seconds early (reference client margins).
SESSION_MARGIN_S = 60
CAPABILITY_MARGIN_S = 20

# Upper bound on PoW solving time so a misbehaving server can't hang a tool call.
POW_TIME_LIMIT_S = 120.0

REQUEST_TIMEOUT_S = 30.0


class AtomicMailAuthError(Exception):
    """Authentication with the Atomic Mail auth service failed."""

    def __init__(self, message: str, *, status_code: int | None = None, hint: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.hint = hint


def decode_jwt_payload(jwt: str) -> dict[str, Any]:
    """Decode a JWT's payload without verifying its signature.

    The client only reads expiry and claims the server put there for it; the
    server verifies the signature on every request.
    """
    parts = jwt.split(".")
    if len(parts) < 2:
        raise ValueError("Malformed JWT: expected at least 2 dot-separated segments")
    payload = parts[1]
    padded = payload + "=" * (-len(payload) % 4)
    data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Malformed JWT: payload is not a JSON object")
    return data


def jwt_expired(jwt: str | None, margin_s: float) -> bool:
    """True when ``jwt`` is missing, unreadable, or expires within ``margin_s``."""
    if not jwt:
        return True
    try:
        exp = decode_jwt_payload(jwt).get("exp")
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return True
    if not isinstance(exp, (int, float)):
        return True
    return time.time() >= exp - margin_s


def has_leading_zero_bits(digest: bytes, bits: int) -> bool:
    """True when the first ``bits`` bits of ``digest`` are all zero."""
    if bits < 0 or bits > len(digest) * 8:
        return False
    full_bytes, remaining = divmod(bits, 8)
    if any(digest[:full_bytes]):
        return False
    if remaining:
        mask = (0xFF << (8 - remaining)) & 0xFF
        return digest[full_bytes] & mask == 0
    return True


def solve_pow(
    challenge: str,
    difficulty: int,
    salt: str,
    time_limit_s: float = POW_TIME_LIMIT_S,
) -> tuple[str, str]:
    """Find a nonce whose scrypt digest has ``difficulty`` leading zero bits.

    Returns ``(pow_hex, nonce)``. The salt is the UTF-8 bytes of the hex text,
    not the decoded bytes; that is what the server hashes.
    """
    deadline = time.monotonic() + time_limit_s
    salt_bytes = salt.encode("utf-8")
    nonce = 0
    while True:
        digest = hashlib.scrypt(
            f"{challenge}:{nonce}".encode(),
            salt=salt_bytes,
            n=SCRYPT_N,
            r=SCRYPT_R,
            p=SCRYPT_P,
            dklen=POW_HASH_BYTES,
        )
        if has_leading_zero_bits(digest, difficulty):
            return digest.hex(), str(nonce)
        nonce += 1
        if time.monotonic() > deadline:
            raise AtomicMailAuthError(f"Proof-of-work not solved within {time_limit_s:.0f}s (difficulty {difficulty} bits)")


def _read_bearer(response: httpx.Response, step: str) -> str:
    header = response.headers.get("Authorization", "")
    if not header.startswith("Bearer ") or not header[7:].strip():
        raise AtomicMailAuthError(f"Atomic Mail {step} response did not include a bearer token")
    return header[7:].strip()


def _raise_for_auth_error(response: httpx.Response, step: str) -> None:
    """Raise AtomicMailAuthError for a non-2xx auth response.

    Error bodies look like ``{"error": {"message": ..., "hint": ...}}``.
    """
    if response.is_success:
        return
    message = f"HTTP {response.status_code}"
    hint = None
    try:
        err = response.json().get("error")
        if isinstance(err, dict):
            message = err.get("message") or message
            hint = err.get("hint")
        elif isinstance(err, str):
            message = err
    except (ValueError, AttributeError):
        pass
    if response.status_code in (401, 403):
        message = f"Invalid Atomic Mail API key ({message})" if step == "session" else message
    raise AtomicMailAuthError(
        f"Atomic Mail {step} failed: {message}",
        status_code=response.status_code,
        hint=hint,
    )


class AtomicMailSession:
    """Holds an API key and the session/capability tokens derived from it.

    Thread-safe: tool calls may run concurrently, and only one of them should
    solve a PoW when tokens expire.
    """

    def __init__(
        self,
        api_key: str,
        *,
        auth_url: str | None = None,
        api_url: str | None = None,
        scrypt_salt: str | None = None,
        inbox_domain: str | None = None,
    ) -> None:
        self._api_key = api_key
        self.auth_url = (auth_url or os.getenv("ATOMIC_MAIL_AUTH_URL") or DEFAULT_AUTH_URL).rstrip("/")
        self.api_url = (api_url or os.getenv("ATOMIC_MAIL_API_URL") or DEFAULT_API_URL).rstrip("/")
        self._salt = scrypt_salt or os.getenv("ATOMIC_MAIL_SCRYPT_SALT") or DEFAULT_SCRYPT_SALT
        self._inbox_domain = (inbox_domain or os.getenv("ATOMIC_MAIL_INBOX_DOMAIN") or DEFAULT_INBOX_DOMAIN).lstrip("@")
        self._lock = threading.Lock()
        self._session_jwt: str | None = None
        self._capability_jwt: str | None = None
        self._inbox_id: str | None = None
        self._jmap_session: dict[str, Any] | None = None
        # Mailbox role -> id. Mailbox ids are stable, so cache them per session.
        self.mailbox_ids: dict[str, str] = {}

    # -- auth service ------------------------------------------------------

    def _login(self) -> None:
        """Solve a fresh PoW challenge and exchange the API key for a session JWT."""
        resp = httpx.post(f"{self.auth_url}/api/v1/challenge", timeout=REQUEST_TIMEOUT_S)
        _raise_for_auth_error(resp, "challenge")
        challenge_jwt = _read_bearer(resp, "challenge")
        try:
            claims = decode_jwt_payload(challenge_jwt)
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as e:
            raise AtomicMailAuthError(f"Atomic Mail challenge token is malformed: {e}") from e
        challenge, difficulty = claims.get("jti"), claims.get("difficulty")
        if not isinstance(challenge, str) or not isinstance(difficulty, int):
            raise AtomicMailAuthError("Atomic Mail challenge token is missing 'jti' or 'difficulty'")

        pow_hex, nonce = solve_pow(challenge, difficulty, self._salt)
        resp = httpx.post(
            f"{self.auth_url}/api/v1/session",
            headers={"Authorization": f"Bearer {challenge_jwt}", "Content-Type": "application/json"},
            json={"powHex": pow_hex, "nonce": nonce, "apiKey": self._api_key},
            timeout=REQUEST_TIMEOUT_S,
        )
        _raise_for_auth_error(resp, "session")
        self._session_jwt = _read_bearer(resp, "session")
        self._capability_jwt = None

    def _mint_capability(self) -> None:
        resp = httpx.post(
            f"{self.auth_url}/api/v1/capability",
            headers={"Authorization": f"Bearer {self._session_jwt}"},
            timeout=REQUEST_TIMEOUT_S,
        )
        _raise_for_auth_error(resp, "capability")
        token = _read_bearer(resp, "capability")
        try:
            inbox_id = decode_jwt_payload(token).get("inboxId")
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            inbox_id = None
        if isinstance(inbox_id, str) and inbox_id:
            self._inbox_id = inbox_id
        self._capability_jwt = token

    def capability_token(self) -> str:
        """Return a capability JWT valid for at least ``CAPABILITY_MARGIN_S``."""
        with self._lock:
            if not jwt_expired(self._capability_jwt, CAPABILITY_MARGIN_S):
                return self._capability_jwt  # type: ignore[return-value]
            if jwt_expired(self._session_jwt, SESSION_MARGIN_S):
                self._login()
            try:
                self._mint_capability()
            except AtomicMailAuthError as e:
                # The server may revoke a session before its exp; log in again once.
                if e.status_code not in (401, 403):
                    raise
                self._login()
                self._mint_capability()
            return self._capability_jwt  # type: ignore[return-value]

    def invalidate_capability(self) -> None:
        """Drop the cached capability token (e.g. after a 401 from JMAP)."""
        with self._lock:
            self._capability_jwt = None

    # -- identity and JMAP session ----------------------------------------

    @property
    def inbox_address(self) -> str | None:
        """The agent's own email address, known after the first capability mint."""
        if not self._inbox_id:
            return None
        if "@" in self._inbox_id:
            return self._inbox_id
        return f"{self._inbox_id}@{self._inbox_domain}"

    def jmap_session(self) -> dict[str, Any]:
        """Fetch (once) the JMAP session resource from ``/.well-known/jmap``."""
        if self._jmap_session is not None:
            return self._jmap_session
        token = self.capability_token()
        resp = httpx.get(
            f"{self.api_url}/.well-known/jmap",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT_S,
        )
        _raise_for_auth_error(resp, "JMAP session discovery")
        data = resp.json()
        account_id = (data.get("primaryAccounts") or {}).get("urn:ietf:params:jmap:mail")
        if not data.get("apiUrl") or not account_id:
            raise AtomicMailAuthError("Atomic Mail JMAP session is missing 'apiUrl' or a mail account")
        self._jmap_session = data
        return data

    @property
    def jmap_api_url(self) -> str:
        return self.jmap_session()["apiUrl"]

    @property
    def account_id(self) -> str:
        return self.jmap_session()["primaryAccounts"]["urn:ietf:params:jmap:mail"]
