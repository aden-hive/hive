"""Outbound messaging for Sentinel — Telegram + Slack.

A deliberately thin, *core-resident* sender. The Slack/Telegram MCP tools
under ``tools/`` are sync and (more importantly) live above core in the
dependency graph, so core cannot import them. This module duplicates the
~10-line REST calls and reads tokens from the shared core credential store
(falling back to env vars), exactly like ``framework.config`` does for LLM
keys.

Tokens are never logged. All I/O is async (``httpx.AsyncClient``), so it
never blocks the event loop.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

CHANNEL_TELEGRAM = "telegram"
CHANNEL_SLACK = "slack"
# Hive Inbox — the first-party, account-bound channel served by hive-backend.
# Unlike telegram/slack it needs no per-channel token: it rides the account's
# existing cloud JWT (HIVE_CLOUD_JWT/HIVE_CLOUD_BASE, same as cloud_sync), so it
# is "connected" whenever the runtime is signed in.
CHANNEL_HIVE = "hive"

_TELEGRAM_API = "https://api.telegram.org"
_SLACK_API = "https://slack.com/api"


@dataclass
class NotifierResult:
    ok: bool
    message_id: str | None = None  # Slack ts / Telegram message_id (as str)
    error: str | None = None


def _credential(cred_id: str, env_var: str) -> str | None:
    """Token from the encrypted credential store, else the env var."""
    if os.environ.get("HIVE_CREDENTIAL_KEY"):
        try:
            from framework.credentials import CredentialStore

            store = CredentialStore.with_encrypted_storage()
            val = store.get(cred_id)
            if isinstance(val, str) and val:
                return val
        except Exception:
            logger.debug("sentinel: credential store lookup failed for %s", cred_id, exc_info=True)
    return os.environ.get(env_var)


def telegram_token() -> str | None:
    return _credential("telegram", "TELEGRAM_BOT_TOKEN")


def slack_bot_token() -> str | None:
    return _credential("slack", "SLACK_BOT_TOKEN")


def slack_app_token() -> str | None:
    """Socket Mode app-level token (``xapp-…``) — distinct from the bot token."""
    return _credential("slack_app", "SLACK_APP_TOKEN")


def hive_backend_base() -> str | None:
    """Base URL of hive-backend, or None. Same env as ``cloud_sync``."""
    return os.environ.get("HIVE_CLOUD_BASE", "").strip() or None


def hive_jwt() -> str | None:
    """The account's cloud JWT, or None. Same env as ``cloud_sync``."""
    return os.environ.get("HIVE_CLOUD_JWT", "").strip() or None


def hive_connected() -> bool:
    """True when the runtime is signed in — i.e. the Hive Inbox channel is
    usable (base URL + JWT present). No per-channel token needed."""
    return bool(hive_backend_base() and hive_jwt())


async def send(
    channel: str,
    target: dict[str, Any],
    text: str,
    thread_ref: dict[str, Any] | None = None,
    *,
    meta: dict[str, Any] | None = None,
) -> NotifierResult:
    """Send ``text`` to ``channel``, optionally threaded under ``thread_ref``.

    ``target`` carries the destination: ``{"chat_id": …}`` for Telegram,
    ``{"channel": …}`` for Slack, ignored for Hive (the JWT identifies the
    account). ``thread_ref`` carries the parent message so a reply lands in the
    same thread: ``{"message_id": …}`` (Telegram) or ``{"ts": …}`` (Slack).

    ``meta`` carries the structured escalation fields the Hive channel POSTs to
    the backend (runtime_id, session_id, colony_id, kind, title, …); it is
    ignored by telegram/slack, which only need ``text``.
    """
    if channel == CHANNEL_TELEGRAM:
        return await _send_telegram(target, text, thread_ref)
    if channel == CHANNEL_SLACK:
        return await _send_slack(target, text, thread_ref)
    if channel == CHANNEL_HIVE:
        return await _send_hive(text, meta or {})
    return NotifierResult(ok=False, error=f"unknown channel {channel!r}")


async def _send_hive(body: str, meta: dict[str, Any]) -> NotifierResult:
    """POST an escalation to hive-backend's Inbox ingest, authed by the account
    JWT. ``meta`` supplies the routing/identity fields; ``body`` is the message
    body. The returned ``message_id`` is the backend row id (the reply anchor)."""
    base = hive_backend_base()
    jwt = hive_jwt()
    if not base or not jwt:
        return NotifierResult(ok=False, error="hive not connected (no cloud JWT/base)")
    payload = {
        "runtime_id": meta.get("runtime_id"),
        "session_id": meta.get("session_id"),
        "colony_id": meta.get("colony_id"),
        "kind": meta.get("kind", "blocker"),
        "title": meta.get("title", ""),
        "body": body,
        "correlation_token": meta.get("correlation_token"),
        "deep_link": meta.get("deep_link"),
    }
    try:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base}/v1/inbox/messages",
                json=payload,
                headers={"Authorization": f"Bearer {jwt}"},
            )
        if resp.status_code >= 300:
            return NotifierResult(ok=False, error=f"hive ingest HTTP {resp.status_code}")
        data = resp.json()
        return NotifierResult(ok=True, message_id=str(data.get("id")) if data.get("id") else None)
    except Exception as e:
        logger.warning("sentinel: hive send failed: %s", e)
        return NotifierResult(ok=False, error=str(e))


async def resolve_hive_session(session_id: str, resolved_by: str = "external") -> bool:
    """Close any open Hive Inbox message for ``session_id`` — used when the
    colony was answered out-of-band (in-app, or another channel) so the Inbox
    doesn't keep showing a stale escalation. Best-effort; no-ops when signed
    out. The backend scopes the resolve to the authenticated account."""
    base = hive_backend_base()
    jwt = hive_jwt()
    if not base or not jwt:
        return False
    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{base}/v1/inbox/resolve",
                json={"session_id": session_id, "resolved_by": resolved_by},
                headers={"Authorization": f"Bearer {jwt}"},
            )
        return resp.status_code < 300
    except Exception as e:
        logger.warning("sentinel: hive resolve failed: %s", e)
        return False


async def _send_telegram(target: dict[str, Any], text: str, thread_ref: dict[str, Any] | None) -> NotifierResult:
    token = telegram_token()
    if not token:
        return NotifierResult(ok=False, error="telegram token not configured")
    chat_id = target.get("chat_id")
    if not chat_id:
        return NotifierResult(ok=False, error="telegram target missing chat_id")
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
    if thread_ref and thread_ref.get("message_id"):
        payload["reply_to_message_id"] = thread_ref["message_id"]
    try:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{_TELEGRAM_API}/bot{token}/sendMessage", json=payload)
        data = resp.json()
        if not data.get("ok"):
            return NotifierResult(ok=False, error=str(data.get("description", "telegram error")))
        mid = data.get("result", {}).get("message_id")
        return NotifierResult(ok=True, message_id=str(mid) if mid is not None else None)
    except Exception as e:
        logger.warning("sentinel: telegram send failed: %s", e)
        return NotifierResult(ok=False, error=str(e))


async def _send_slack(target: dict[str, Any], text: str, thread_ref: dict[str, Any] | None) -> NotifierResult:
    token = slack_bot_token()
    if not token:
        return NotifierResult(ok=False, error="slack token not configured")
    channel = target.get("channel")
    if not channel:
        return NotifierResult(ok=False, error="slack target missing channel")
    payload: dict[str, Any] = {"channel": channel, "text": text}
    if thread_ref and thread_ref.get("ts"):
        payload["thread_ts"] = thread_ref["ts"]
    try:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{_SLACK_API}/chat.postMessage",
                json=payload,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
            )
        data = resp.json()
        if not data.get("ok"):
            return NotifierResult(ok=False, error=str(data.get("error", "slack error")))
        return NotifierResult(ok=True, message_id=data.get("ts"))
    except Exception as e:
        logger.warning("sentinel: slack send failed: %s", e)
        return NotifierResult(ok=False, error=str(e))
