"""Sentinel configuration + connect routes.

Backs the colony Automation-tab "Sentinel" section in the desktop UI:

- GET  /api/colony/{colony_id}/notifications        — current per-colony config + channel status
- PUT  /api/colony/{colony_id}/notifications        — save config (enable/channel/target/allowlist)
- POST /api/colony/{colony_id}/notifications/test   — send a test message to the configured destination
- GET  /api/sentinel/credentials                    — which channel tokens are configured
- POST /api/sentinel/telegram/validate              — validate a bot token (getMe)
- POST /api/sentinel/telegram/detect-chat           — discover the chat id after the user DMs the bot (getUpdates)
- POST /api/sentinel/slack/validate                 — validate a bot token (auth.test)

Tokens themselves are saved through the existing /api/credentials endpoint
(encrypted store, ids: telegram / slack / slack_app); these routes only read
token presence and exercise the channel APIs for the connect wizard.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from aiohttp import web

from framework.host.colony_metadata import colony_metadata_path
from framework.sentinel import notifier, store

logger = logging.getLogger(__name__)

_VALID_CHANNELS = {"hive", "telegram", "slack"}


def _colony_missing(colony_id: str) -> web.Response | None:
    if not colony_metadata_path(colony_id).exists():
        return web.json_response({"error": f"Colony '{colony_id}' not found"}, status=404)
    return None


def _channel_status() -> dict[str, Any]:
    return {
        "telegram": {"configured": bool(notifier.telegram_token())},
        "slack": {
            "bot": bool(notifier.slack_bot_token()),
            "app": bool(notifier.slack_app_token()),
        },
    }


def _config_payload(colony_id: str) -> dict[str, Any]:
    cfg = store.load_notifications_config(colony_id)
    return {
        "colony_id": colony_id,
        "sentinel_enabled": cfg.sentinel_enabled,
        "channel": cfg.channel,
        "target": cfg.target,
        "allowlist": cfg.allowlist,
        "thread": cfg.thread,
        "classify_after_seconds": cfg.classify_after_seconds,
        "credentials": _channel_status(),
    }


# ----- per-colony config --------------------------------------------------


async def handle_get_notifications(request: web.Request) -> web.Response:
    colony_id = request.match_info["colony_id"]
    if (missing := _colony_missing(colony_id)) is not None:
        return missing
    return web.json_response(_config_payload(colony_id))


async def handle_put_notifications(request: web.Request) -> web.Response:
    colony_id = request.match_info["colony_id"]
    if (missing := _colony_missing(colony_id)) is not None:
        return missing
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "Body must be a JSON object"}, status=400)

    channel = body.get("channel")
    enabled = bool(body.get("sentinel_enabled", False))
    if enabled and channel not in _VALID_CHANNELS:
        return web.json_response({"error": "channel must be 'telegram' or 'slack' when enabled"}, status=400)
    target = body.get("target") if isinstance(body.get("target"), dict) else {}
    allow = body.get("allowlist") or []
    if not isinstance(allow, list):
        return web.json_response({"error": "allowlist must be a list"}, status=400)

    # Optional per-colony idle budget; null/absent clears the override.
    cas_raw = body.get("classify_after_seconds")
    classify_after_seconds: float | None = None
    if cas_raw is not None:
        try:
            classify_after_seconds = float(cas_raw)
        except (TypeError, ValueError):
            return web.json_response({"error": "classify_after_seconds must be a number or null"}, status=400)
        if classify_after_seconds <= 0:
            return web.json_response({"error": "classify_after_seconds must be positive"}, status=400)

    try:
        store.update_notifications_config(
            colony_id,
            sentinel_enabled=enabled,
            channel=channel,
            target=target,
            allowlist=[str(x) for x in allow],
            classify_after_seconds=classify_after_seconds,
        )
    except FileNotFoundError:
        return web.json_response({"error": f"Colony '{colony_id}' not found"}, status=404)

    # Start the inbound listener now if the user just connected a channel —
    # so two-way works without a restart.
    try:
        from framework.sentinel.manager import get_sentinel_manager

        mgr = get_sentinel_manager()
        if mgr is not None:
            mgr.refresh_listeners()
    except Exception:
        logger.debug("sentinel: refresh_listeners after config save failed", exc_info=True)

    return web.json_response(_config_payload(colony_id))


async def handle_test_notification(request: web.Request) -> web.Response:
    colony_id = request.match_info["colony_id"]
    if (missing := _colony_missing(colony_id)) is not None:
        return missing
    cfg = store.load_notifications_config(colony_id)
    # Allow overriding channel/target from the body for a pre-save test.
    try:
        body = await request.json()
    except Exception:
        body = {}
    channel = (body or {}).get("channel") or cfg.channel
    target = (body or {}).get("target") or cfg.target
    if channel not in _VALID_CHANNELS or not target:
        return web.json_response({"error": "channel and target required to send a test"}, status=400)

    result = await notifier.send(
        channel,
        target,
        f'✅ Sentinel test for colony "{colony_id}". If you can read this, replies will reach the queen.',
        None,
    )
    return web.json_response({"ok": result.ok, "message_id": result.message_id, "error": result.error})


# ----- global credential status -------------------------------------------


async def handle_credential_status(request: web.Request) -> web.Response:
    return web.json_response(_channel_status())


# ----- channel connect helpers --------------------------------------------


async def handle_telegram_validate(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        body = {}
    token = (body or {}).get("token") or notifier.telegram_token()
    if not token:
        return web.json_response({"ok": False, "error": "no token provided or saved"}, status=400)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"https://api.telegram.org/bot{token}/getMe")
        data = resp.json()
        if not data.get("ok"):
            return web.json_response({"ok": False, "error": data.get("description", "invalid token")})
        result = data.get("result", {})
        return web.json_response({"ok": True, "bot_username": result.get("username"), "bot_name": result.get("first_name")})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})


async def handle_telegram_detect_chat(request: web.Request) -> web.Response:
    """Discover the chat id after the user DMs the bot. Returns the most
    recent sender so the UI can fill chat id + add them to the allowlist."""
    token = notifier.telegram_token()
    if not token:
        return web.json_response({"ok": False, "error": "save the bot token first"}, status=400)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # offset=-1 → just the latest update; tolerate a running listener.
            resp = await client.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"offset": -1, "limit": 1, "allowed_updates": '["message"]'},
            )
        data = resp.json()
        if not data.get("ok"):
            return web.json_response({"ok": False, "error": data.get("description", "getUpdates failed")})
        updates = data.get("result", [])
        if not updates:
            return web.json_response({"ok": False, "pending": True, "error": "No message yet — send any message to your bot, then retry."})
        msg = updates[-1].get("message", {})
        chat = msg.get("chat", {})
        sender = msg.get("from", {})
        return web.json_response(
            {
                "ok": True,
                "chat_id": str(chat.get("id")) if chat.get("id") is not None else None,
                "chat_title": chat.get("title") or chat.get("first_name") or chat.get("username"),
                "sender_id": str(sender.get("id")) if sender.get("id") is not None else None,
                "sender_name": sender.get("username") or sender.get("first_name"),
            }
        )
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})


async def handle_slack_validate(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        body = {}
    token = (body or {}).get("token") or notifier.slack_bot_token()
    if not token:
        return web.json_response({"ok": False, "error": "no token provided or saved"}, status=400)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://slack.com/api/auth.test",
                headers={"Authorization": f"Bearer {token}"},
            )
        data = resp.json()
        if not data.get("ok"):
            return web.json_response({"ok": False, "error": data.get("error", "invalid token")})
        return web.json_response({"ok": True, "team": data.get("team"), "bot_user": data.get("user")})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})


def register_routes(app: web.Application) -> None:
    app.router.add_get("/api/colony/{colony_id}/notifications", handle_get_notifications)
    app.router.add_put("/api/colony/{colony_id}/notifications", handle_put_notifications)
    app.router.add_post("/api/colony/{colony_id}/notifications/test", handle_test_notification)
    app.router.add_get("/api/sentinel/credentials", handle_credential_status)
    app.router.add_post("/api/sentinel/telegram/validate", handle_telegram_validate)
    app.router.add_post("/api/sentinel/telegram/detect-chat", handle_telegram_detect_chat)
    app.router.add_post("/api/sentinel/slack/validate", handle_slack_validate)
