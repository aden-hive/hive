"""
streamtoken_refresh — in-VM background job that rotates the runtime's own
``hive`` streamToken before the 24h TTL expires.

Why this exists
---------------
Before this, the desktop client owned all streamToken refreshes:
``hive-desktop/src/main/cloud.ts:refreshStreamToken`` ran a periodic
health-check, minted a fresh token via ``POST /user/refresh-stream-token``
(authenticated by the user's full JWT), and pushed the new token into
the VM via ``configureRemoteLlm`` (POST /api/credentials).

That coupled "cloud queens can call LLMs" to "the desktop is online" —
if the laptop closed or the network dropped, the VM's stored token
expired within 24h and every LLM call hit
``hive_stream_token_invalid`` from the hive-llm proxy.

This module breaks that dependency. The runtime knows its own
streamToken (it's the ``hive`` credential in its credential store). It
calls a new backend endpoint, ``POST /user/refresh-stream-token-from-stream``,
which validates the streamToken's signature directly (no user-JWT
needed — the streamToken signature IS proof of identity, and the
endpoint refuses post-expiry refresh so revocation is still possible
via sid-blacklist or master-secret rotation).

Behavior
--------
* Reads the current token from the credential store; sleeps if absent
  (the desktop hasn't pushed yet — common on first boot before
  configureRemoteLlm fires).
* Decodes the JWT's ``exp`` claim (manual base64 decode, no new dep).
* Refresh threshold: ``REFRESH_BEFORE_SECONDS = 7200`` (2h). Matches
  the desktop's ``STREAM_REFRESH_THRESHOLD_MS`` so the two paths agree
  on what "close to expiry" means.
* Re-runs roughly every (exp - threshold - now) seconds, bounded by
  ``MIN_SLEEP_SECONDS = 60`` (no tight loops on bad clocks) and
  ``MAX_SLEEP_SECONDS = 3600`` (re-check at least hourly even if
  ``exp`` is way out).
* On success: writes the new token back to the credential store (under
  the same ``hive`` id) via ``save_credential``. The cache invalidation
  is built into ``save_credential``; the next LLM call reads the fresh
  token automatically.
* On failure: warn-logs, never crashes the loop, retries on the next
  tick.
* Exposes ``app["streamtoken_force_refresh"]`` so the LiteLLM call
  site can demand an immediate refresh after seeing
  ``hive_stream_token_invalid`` — defense-in-depth that catches the
  window where the refresh job hasn't ticked yet but the token is
  already rejected (clock skew, manual revocation, etc.).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from pydantic import SecretStr

from framework.credentials.models import CredentialKey, CredentialObject

logger = logging.getLogger(__name__)

CREDENTIAL_ID = "hive"
KEY_NAME = "api_key"

# Refresh when <= this many seconds remain on the current token. 2h
# mirrors the desktop's STREAM_REFRESH_THRESHOLD_MS = 2 * 60 * 60_000
# so the two refresh sources have a coherent definition of "stale".
REFRESH_BEFORE_SECONDS = 7200

# Bounds on how long the loop sleeps between ticks. Min avoids burning
# CPU when a token is already past-due (e.g. clock skew, manual rotation
# inserted a short-TTL token); max ensures we re-check periodically
# even with a freshly-minted 24h token (defense against drift between
# our exp computation and reality).
MIN_SLEEP_SECONDS = 60
MAX_SLEEP_SECONDS = 3600

# Set to true via app["streamtoken_force_refresh"]() to demand an
# immediate refresh attempt (next loop iteration). Used by the LLM
# call site on hive_stream_token_invalid.
_force_refresh_event_key = "streamtoken_force_refresh_event"


# ---------------------------------------------------------------------------
# Pure helpers (testable without aiohttp / httpx)
# ---------------------------------------------------------------------------


def decode_jwt_exp(token: str) -> int | None:
    """Read the ``exp`` claim from a JWT WITHOUT verifying the signature.

    Returns the unix-timestamp ``exp`` value, or ``None`` if the token
    is malformed or has no exp claim. Used only to decide when to
    refresh — the actual signature is validated server-side at refresh
    time, and at every LLM call by the Rust proxy.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        # JWT base64url, no padding. Pad to a multiple of 4 so
        # urlsafe_b64decode accepts it.
        payload_b = parts[1].encode("ascii")
        payload_b += b"=" * (-len(payload_b) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b).decode("utf-8"))
        exp = payload.get("exp")
        if isinstance(exp, (int, float)):
            return int(exp)
        return None
    except Exception:
        return None


def compute_sleep_seconds(
    exp_unix: int | None,
    now_unix: float,
    refresh_before_seconds: int = REFRESH_BEFORE_SECONDS,
    min_sleep: int = MIN_SLEEP_SECONDS,
    max_sleep: int = MAX_SLEEP_SECONDS,
) -> int:
    """How long to sleep before the next refresh check.

    * ``exp_unix is None`` → token unparseable or exp missing; sleep
      ``min`` so a corrupted/missing credential gets re-checked
      quickly (probably waiting for the desktop's first push).
    * Token expires in <= ``refresh_before_seconds`` → sleep ``min``
      so we refresh on the next tick.
    * Otherwise → sleep until ``(exp - refresh_before - now)``,
      bounded by ``[min, max]``.
    """
    if exp_unix is None:
        return min_sleep
    seconds_until_refresh = exp_unix - refresh_before_seconds - now_unix
    if seconds_until_refresh <= min_sleep:
        return min_sleep
    if seconds_until_refresh > max_sleep:
        return max_sleep
    return int(seconds_until_refresh)


# ---------------------------------------------------------------------------
# Network — refresh-from-stream endpoint
# ---------------------------------------------------------------------------


async def post_refresh(
    base_url: str,
    current_token: str,
    *,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
) -> str | None:
    """Call ``POST /user/refresh-stream-token-from-stream`` with the
    current token. Returns the new streamToken on success, ``None`` on
    failure (logged at warn).

    ``client_factory`` is dependency-injected so tests can hand back a
    mocked httpx client without monkey-patching the module.
    """
    url = f"{base_url.rstrip('/')}/user/refresh-stream-token-from-stream"
    factory: Callable[[], httpx.AsyncClient] = client_factory or (lambda: httpx.AsyncClient(timeout=15.0))
    try:
        async with factory() as client:
            resp = await client.post(url, json={"streamToken": current_token})
        if resp.status_code != 200:
            logger.warning(
                "streamtoken_refresh: backend returned %s: %s",
                resp.status_code,
                resp.text[:200],
            )
            return None
        body = resp.json()
        new_token = body.get("streamToken")
        if not isinstance(new_token, str) or not new_token:
            logger.warning("streamtoken_refresh: response missing streamToken")
            return None
        return new_token
    except Exception:
        logger.warning("streamtoken_refresh: POST failed", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Loop + aiohttp registration
# ---------------------------------------------------------------------------


def _read_current_token(store: Any) -> str | None:
    """Pull the ``hive`` credential's ``api_key`` value out of the
    store, or return ``None`` if absent or unreadable. ``Any`` typed
    because the credential store class lives in a circular-import-prone
    module; the duck-typed API is ``get_credential(id) -> CredentialObject | None``
    and ``CredentialObject.get_key(name) -> str | None``.
    """
    try:
        cred = store.get_credential(CREDENTIAL_ID)
        if cred is None:
            return None
        return cred.get_key(KEY_NAME)
    except Exception:
        logger.warning("streamtoken_refresh: failed to read credential", exc_info=True)
        return None


def _save_token(store: Any, token: str) -> bool:
    try:
        cred = CredentialObject(
            id=CREDENTIAL_ID,
            keys={
                KEY_NAME: CredentialKey(name=KEY_NAME, value=SecretStr(token)),
            },
        )
        store.save_credential(cred)
        return True
    except Exception:
        logger.warning("streamtoken_refresh: failed to save credential", exc_info=True)
        return False


async def _refresh_loop(
    app: Any,
    *,
    post_refresh_fn: Callable[[str, str], Awaitable[str | None]] | None = None,
    now_fn: Callable[[], float] | None = None,
    sleep_fn: Callable[[float], Awaitable[None]] | None = None,
) -> None:
    """The background coroutine. DI hooks at the bottom are for tests
    to inject a fake clock + fake refresh call so we can deterministically
    drive the loop through near-expiry, refresh-success, and
    refresh-failure paths."""
    now = now_fn or (lambda: __import__("time").time())
    sleep = sleep_fn or asyncio.sleep
    refresh = post_refresh_fn or (
        lambda base, tok: post_refresh(base, tok)  # type: ignore[arg-type]
    )

    base_url = os.environ.get("HIVE_CLOUD_BASE", "").rstrip("/")
    if not base_url:
        logger.info("streamtoken_refresh: disabled (no HIVE_CLOUD_BASE — runtime not in cloud mode)")
        return

    store = app.get("credential_store") if hasattr(app, "get") else app["credential_store"]
    force_event: asyncio.Event = app[_force_refresh_event_key]

    logger.info(
        "streamtoken_refresh: started (threshold=%ds, min_sleep=%ds, max_sleep=%ds, base=%s)",
        REFRESH_BEFORE_SECONDS,
        MIN_SLEEP_SECONDS,
        MAX_SLEEP_SECONDS,
        base_url,
    )

    while True:
        try:
            token = _read_current_token(store)
            if not token:
                # No `hive` credential yet — desktop hasn't pushed via
                # configureRemoteLlm. Wait briefly and re-check.
                await _sleep_with_force(sleep, force_event, MIN_SLEEP_SECONDS)
                continue

            exp = decode_jwt_exp(token)
            sleep_seconds = compute_sleep_seconds(exp, now())

            # Wait — but cut short if the LLM call site demands a force
            # refresh.
            await _sleep_with_force(sleep, force_event, sleep_seconds)

            # Re-read after the sleep — desktop may have pushed a fresh
            # token in the meantime, in which case ours might already
            # be valid. Cheap to re-check.
            current = _read_current_token(store)
            if not current:
                continue
            current_exp = decode_jwt_exp(current)
            now_unix = now()
            if current_exp is not None and current_exp - now_unix > REFRESH_BEFORE_SECONDS and not force_event.is_set():
                # Someone else (desktop) just refreshed it. Re-loop and
                # compute the new sleep from this fresher exp.
                continue
            force_event.clear()

            new_token = await refresh(base_url, current)
            if new_token:
                if _save_token(store, new_token):
                    new_exp = decode_jwt_exp(new_token)
                    logger.info(
                        "streamtoken_refresh: rotated token (new_exp=%s, %ds from now)",
                        new_exp,
                        (new_exp or 0) - int(now_unix),
                    )
            # Refresh failed — log already happened in post_refresh.
            # Next tick will retry; clear the force flag so we don't
            # busy-loop on a persistent backend outage.
            force_event.clear()
        except asyncio.CancelledError:
            logger.info("streamtoken_refresh: cancelled")
            raise
        except Exception:
            logger.warning("streamtoken_refresh: tick failed", exc_info=True)
            await sleep(MIN_SLEEP_SECONDS)


async def _sleep_with_force(
    sleep_fn: Callable[[float], Awaitable[None]],
    force_event: asyncio.Event,
    seconds: float,
) -> None:
    """Sleep for ``seconds``, but return early if ``force_event`` is
    set. Lets the LLM call site short-circuit the next refresh after
    seeing hive_stream_token_invalid."""
    try:
        await asyncio.wait_for(force_event.wait(), timeout=seconds)
    except TimeoutError:
        pass
    else:
        # Cleared inside the loop after action.
        pass


# ---------------------------------------------------------------------------
# Module-level "refresh now" hook for the LLM call site
# ---------------------------------------------------------------------------
#
# When ``litellm.acompletion`` gets back ``hive_stream_token_invalid``
# from the Rust proxy, it's racing the refresh loop: the token expired
# (or was revoked) and the loop hasn't ticked yet. The defensive path
# is to immediately call the refresh endpoint, swap in the new token,
# and retry the LLM call once. ``try_refresh_now()`` is the entry
# point. We hold module-level references to the credential store and
# base URL so the LLM call site doesn't need to thread the aiohttp
# ``app`` object through itself.
#
# Set at ``start_streamtoken_refresh`` time; remain ``None`` outside
# the in-VM hive serve context (e.g. when running unit tests without
# the server, or when the desktop runtime boots without HIVE_CLOUD_BASE).
# In those cases ``try_refresh_now()`` returns ``None`` without erroring,
# and the call site falls back to whatever next-step logic it has.

_credential_store_ref: Any = None
_aden_base_url_ref: str | None = None
_refresh_now_lock: asyncio.Lock | None = None


async def try_refresh_now() -> str | None:
    """Force-refresh the streamToken right now. Safe to call from any
    coroutine; concurrent callers serialize on ``_refresh_now_lock``
    (one refresh per fire). Returns the new token (and writes it to the
    credential store) on success, ``None`` on failure or when refresh
    isn't configured.

    Idempotent under racing LLM calls: if N coroutines see
    ``hive_stream_token_invalid`` simultaneously, the lock ensures
    exactly one POST to the backend; the rest pick up the cached
    fresh token on their retry by re-reading from the credential store."""
    global _refresh_now_lock
    if _credential_store_ref is None or _aden_base_url_ref is None:
        return None
    if _refresh_now_lock is None:
        # Lazy-init so this works whether or not the event loop was the
        # one start_streamtoken_refresh ran on (matters in tests).
        _refresh_now_lock = asyncio.Lock()
    async with _refresh_now_lock:
        current = _read_current_token(_credential_store_ref)
        if not current:
            return None
        # If the credential was refreshed while we waited for the lock
        # (another caller went through this same path concurrently),
        # the token in the store may now be fresh enough that calling
        # the backend again would be wasteful. "Fresh enough" = exp
        # comfortably past the refresh threshold — anything tighter
        # might be the very token the caller was just rejected for,
        # so we still need to refresh.
        import time as _time

        exp = decode_jwt_exp(current)
        if exp is not None and exp - _time.time() > REFRESH_BEFORE_SECONDS:
            logger.debug(
                "streamtoken_refresh: forced refresh skipped — credential was already refreshed concurrently (exp=%s)",
                exp,
            )
            return current
        new_token = await post_refresh(_aden_base_url_ref, current)
        if not new_token:
            return None
        if not _save_token(_credential_store_ref, new_token):
            # Saved-but-failed shouldn't happen with the existing store
            # impl, but if it does, returning the token lets the caller
            # at least retry with the live value in memory.
            return new_token
        logger.info("streamtoken_refresh: forced refresh succeeded")
        return new_token


async def start_streamtoken_refresh(app: Any) -> None:
    """aiohttp ``on_startup`` hook — registered alongside
    ``start_cloud_sync`` in ``framework.server.app.create_app``."""
    global _credential_store_ref, _aden_base_url_ref, _refresh_now_lock
    app[_force_refresh_event_key] = asyncio.Event()

    def _force_refresh() -> None:
        """Wake the refresh loop early. Idempotent — multiple calls
        between ticks collapse into a single forced tick."""
        event: asyncio.Event = app[_force_refresh_event_key]
        event.set()

    app["streamtoken_force_refresh"] = _force_refresh
    # Capture module-level refs so try_refresh_now() works from the
    # LLM call site without needing access to the app.
    _credential_store_ref = app.get("credential_store") if hasattr(app, "get") else app["credential_store"]
    _aden_base_url_ref = os.environ.get("HIVE_CLOUD_BASE", "").rstrip("/") or None
    _refresh_now_lock = asyncio.Lock()
    app["streamtoken_refresh_task"] = asyncio.create_task(_refresh_loop(app))
