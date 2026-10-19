"""Inbound listeners — receive user replies and hand them to the manager.

Both channels use *outbound* connections, which work behind NAT (the runtime
is on localhost): Telegram via ``getUpdates`` long-poll, Slack via Socket
Mode. Each runs as a single process-global task — both APIs are
single-connection per token, so running two pollers would conflict.

These never raise out: on any error they log and back off, so a flaky network
can't take down the manager. They simply forward parsed messages to
``SentinelManager.on_inbound``; all auth/routing/resume lives there.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

from framework.sentinel import notifier

if TYPE_CHECKING:
    from framework.sentinel.manager import SentinelManager

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org"
_SLACK_API = "https://slack.com/api"


class TelegramListener:
    def __init__(self, manager: SentinelManager) -> None:
        self._manager = manager

    async def run(self) -> None:
        tok = notifier.telegram_token()
        if not tok:
            return
        import httpx

        offset: int | None = None
        logger.info("[sentinel] telegram listener started")
        # Long-poll timeout is 30s server-side; give the client a bit more.
        async with httpx.AsyncClient(timeout=45.0) as client:
            while True:
                try:
                    params: dict[str, object] = {"timeout": 30, "allowed_updates": json.dumps(["message"])}
                    if offset is not None:
                        params["offset"] = offset
                    resp = await client.get(f"{_TELEGRAM_API}/bot{tok}/getUpdates", params=params)
                    data = resp.json()
                    for upd in data.get("result", []):
                        offset = int(upd["update_id"]) + 1
                        await self._handle_update(upd)
                except asyncio.CancelledError:
                    logger.info("[sentinel] telegram listener stopped")
                    return
                except Exception:
                    logger.debug("[sentinel] telegram poll error", exc_info=True)
                    await asyncio.sleep(3.0)

    async def _handle_update(self, upd: dict) -> None:
        msg = upd.get("message") or {}
        chat = msg.get("chat") or {}
        frm = msg.get("from") or {}
        sender = str(frm.get("id", ""))
        chat_id = str(chat.get("id", ""))
        # Record the chat for ``sentinel_setup detect_chat`` BEFORE the text gate
        # (a "Start" tap / any message is enough to identify the chat). This is
        # the only way detect_chat can learn the chat while this listener is
        # running — it consumes updates, so a direct getUpdates would see none.
        if chat_id:
            self._manager.record_recent_chat(
                "telegram",
                chat_id=chat_id,
                sender_id=sender,
                chat_title=chat.get("title") or chat.get("first_name") or chat.get("username") or "",
                sender_name=frm.get("username") or frm.get("first_name") or "",
            )
        text = msg.get("text") or ""
        if not text:
            return
        thread_ref: dict[str, object] = {}
        rt = msg.get("reply_to_message")
        if rt and rt.get("message_id") is not None:
            thread_ref = {"message_id": rt["message_id"]}
        await self._manager.on_inbound("telegram", sender, text, thread_ref, source=chat_id)


class SlackSocketListener:
    def __init__(self, manager: SentinelManager) -> None:
        self._manager = manager

    async def run(self) -> None:
        app_token = notifier.slack_app_token()
        if not app_token:
            return
        import aiohttp

        logger.info("[sentinel] slack socket-mode listener started")
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    wss_url = await self._open_socket(session, app_token)
                    if not wss_url:
                        await asyncio.sleep(5.0)
                        continue
                    async with session.ws_connect(wss_url) as ws:
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                await self._handle_ws_message(ws, msg.data)
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
            except asyncio.CancelledError:
                logger.info("[sentinel] slack listener stopped")
                return
            except Exception:
                logger.debug("[sentinel] slack socket error", exc_info=True)
                await asyncio.sleep(5.0)

    async def _open_socket(self, session, app_token: str) -> str | None:
        async with session.post(
            f"{_SLACK_API}/apps.connections.open",
            headers={"Authorization": f"Bearer {app_token}"},
        ) as resp:
            data = await resp.json()
        if not data.get("ok"):
            logger.warning("[sentinel] slack apps.connections.open failed: %s", data.get("error"))
            return None
        return data.get("url")

    async def _handle_ws_message(self, ws, raw: str) -> None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        # Ack every enveloped message so Slack doesn't retry it.
        envelope_id = data.get("envelope_id")
        if envelope_id:
            await ws.send_json({"envelope_id": envelope_id})
        if data.get("type") != "events_api":
            return
        event = (data.get("payload") or {}).get("event") or {}
        if event.get("type") != "message":
            return
        # Ignore bot echoes (including our own outbound messages).
        if event.get("bot_id") or event.get("subtype"):
            return
        text = event.get("text") or ""
        if not text:
            return
        sender = str(event.get("user", ""))
        channel = str(event.get("channel", ""))
        thread_ref = {"ts": event.get("thread_ts") or event.get("ts")}
        await self._manager.on_inbound("slack", sender, text, thread_ref, source=channel)


class HiveInboxListener:
    """Outbound SSE subscription to hive-backend's runtime reply-stream.

    Mirrors :class:`TelegramListener`: a single long-lived outbound connection
    (NAT-friendly) that self-registers this runtime and receives replies the
    user posted from any client. Each reply is wrapped with the escalation's
    ``(ref: …)`` token so it routes through the existing :meth:`on_inbound`
    resolution exactly like a quoted Telegram/Slack reply.
    """

    def __init__(self, manager: SentinelManager) -> None:
        self._manager = manager

    async def run(self) -> None:
        from framework.sentinel import notifier, runtime_identity

        base = notifier.hive_backend_base()
        jwt = notifier.hive_jwt()
        if not base or not jwt:
            return
        rid = runtime_identity.get_runtime_id()
        kind = runtime_identity.get_runtime_kind()
        url = f"{base}/v1/inbox/runtime/stream"
        params = {"runtime_id": rid, "kind": kind}
        headers = {"Authorization": f"Bearer {jwt}", "Accept": "text/event-stream"}

        import httpx

        logger.info("[sentinel] hive inbox listener started (runtime_id=%s kind=%s)", rid, kind)
        while True:
            try:
                # No read timeout: the stream is idle between replies (the
                # server sends ``: ping`` comments to keep it alive).
                timeout = httpx.Timeout(30.0, read=None)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream("GET", url, params=params, headers=headers) as resp:
                        if resp.status_code != 200:
                            logger.warning("[sentinel] hive stream HTTP %s", resp.status_code)
                            await asyncio.sleep(5.0)
                            continue
                        await self._consume(resp)
            except asyncio.CancelledError:
                logger.info("[sentinel] hive inbox listener stopped")
                return
            except Exception:
                logger.debug("[sentinel] hive stream error", exc_info=True)
                await asyncio.sleep(3.0)

    async def _consume(self, resp) -> None:
        """Parse the SSE frames on an open stream, dispatching ``reply`` events."""
        event = "message"
        data_lines: list[str] = []
        async for line in resp.aiter_lines():
            if line == "":  # frame boundary — dispatch what we accumulated
                if data_lines:
                    await self._handle_event(event, "\n".join(data_lines))
                event = "message"
                data_lines = []
                continue
            if line.startswith(":"):  # comment / keepalive
                continue
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())

    async def _handle_event(self, event: str, raw: str) -> None:
        if event != "reply":
            return
        from framework.sentinel import token

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return
        tok = data.get("correlation_token")
        reply = data.get("text") or ""
        if not tok or not reply:
            return
        # Wrap with the (ref: token) footer so on_inbound resolves by token,
        # then strips it before injecting the reply into the queen.
        envelope = f"{token.format_ref(tok)} {reply}"
        await self._manager.on_inbound("hive", "hive", envelope, None, source=data.get("colony_id"))
