"""Sentinel manager — outbound delivery, inbound routing, and resume.

One process-global instance, started in ``cmd_serve.run_server`` and reachable
via :func:`get_sentinel_manager` from the in-loop :class:`EscalationSource`. It:

  * drains escalation payloads (enqueued non-blockingly from the loop), writes
    the on-disk record, and delivers the message via :mod:`notifier`;
  * runs the inbound listeners (Telegram long-poll / Slack Socket Mode) and
    routes a reply back to the parked queen via ``inject_event``;
  * answers "is a desktop UI attached?" for the escalate gate.

Disk is the source of truth: on :meth:`start` it rebuilds the in-memory
token index from open records so a reply after a restart still resolves.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from framework.sentinel import notifier, store, token

logger = logging.getLogger(__name__)

# Markdown **bold** → Slack/Telegram mrkdwn *bold*. The queen's text is authored
# in UI-markdown (double-asterisk); both channels render single-asterisk, so
# without this the user sees literal ``**`` around the text.
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)


def _to_mrkdwn(text: str) -> str:
    return _BOLD_RE.sub(r"*\1*", text)


_instance: SentinelManager | None = None


def get_sentinel_manager() -> SentinelManager | None:
    return _instance


def set_sentinel_manager(mgr: SentinelManager | None) -> None:
    global _instance
    _instance = mgr


def _install_sentinel_log_file() -> None:
    """Opt-in: divert the whole ``framework.sentinel.*`` namespace to a
    dedicated rotating file so a long debug session can watch sentinel in
    isolation (``tail -f ~/.hive/logs/sentinel.log``) instead of hunting it in
    the mixed main stream.

    Enabled only when ``HIVE_SENTINEL_LOG`` is set (truthy). When on, sentinel
    logs go to the file at DEBUG and are kept *off* the main stdout/stderr
    (``propagate = False``). When off this is a no-op — default behaviour is
    unchanged. Idempotent.
    """
    import os

    if not os.environ.get("HIVE_SENTINEL_LOG"):
        return
    from logging.handlers import RotatingFileHandler

    from framework.config import HIVE_HOME

    pkg_logger = logging.getLogger("framework.sentinel")
    if any(getattr(h, "_sentinel_file", False) for h in pkg_logger.handlers):
        return  # already installed

    log_dir = HIVE_HOME / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "sentinel.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    handler._sentinel_file = True  # idempotency marker
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s"))
    pkg_logger.addHandler(handler)
    pkg_logger.setLevel(logging.DEBUG)
    # Keep sentinel chatter out of the main console — the file is the one window.
    pkg_logger.propagate = False
    logger.info("[sentinel] logging to %s", log_dir / "sentinel.log")


class SentinelManager:
    def __init__(self, session_manager: Any) -> None:
        self._session_manager = session_manager
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._tasks: list[asyncio.Task] = []
        # token -> (colony_id, escalation_id)
        self._by_token: dict[str, tuple[str, str]] = {}
        # Named inbound listener tasks (so refresh can start them once-only).
        self._listeners: dict[str, asyncio.Task] = {}
        # Most-recent inbound chat per channel (set by the listeners on every
        # message). Lets ``sentinel_setup detect_chat`` read the chat the daemon
        # already consumed — a competing getUpdates can't see it, since the
        # Telegram listener acks updates by advancing the offset. channel ->
        # {chat_id, sender_id, chat_title, sender_name, at}.
        self._recent_chats: dict[str, dict[str, Any]] = {}

    # ----- lifecycle ------------------------------------------------------

    async def start(self) -> None:
        _install_sentinel_log_file()
        # Rebuild the token index from disk (survives restarts).
        for rec in store.list_all_open():
            if rec.correlation_token:
                self._by_token[rec.correlation_token] = (rec.colony_id, rec.escalation_id)
        logger.info("[sentinel] manager starting (%d open escalations)", len(self._by_token))

        self._tasks.append(asyncio.create_task(self._drain_escalations(), name="sentinel_sender"))
        # Start whichever inbound listeners already have a token; the rest are
        # started on demand via refresh_listeners() when a token is connected.
        self.refresh_listeners()

    def refresh_listeners(self) -> None:
        """(Re)start inbound listeners for channels that now have a token.

        Idempotent — a listener already running for a channel is left alone.
        Called at startup and again from the config route after a user
        connects a channel, so connecting works without a restart.
        """
        from framework.sentinel.listeners import (
            HiveInboxListener,
            SlackSocketListener,
            TelegramListener,
        )

        def _ensure(name: str, has_token: bool, make):
            existing = self._listeners.get(name)
            if has_token and (existing is None or existing.done()):
                task = asyncio.create_task(make().run(), name=f"sentinel_{name}")
                self._listeners[name] = task
                logger.info("[sentinel] %s listener started", name)

        _ensure("telegram", bool(notifier.telegram_token()), lambda: TelegramListener(self))
        _ensure("slack", bool(notifier.slack_app_token()), lambda: SlackSocketListener(self))
        # Hive Inbox needs no per-channel token — just a signed-in account.
        _ensure("hive", notifier.hive_connected(), lambda: HiveInboxListener(self))

    def is_listening(self, channel: str) -> bool:
        """True when an inbound listener for ``channel`` is currently running.

        When true, that listener owns the update stream (Telegram getUpdates is
        single-consumer), so ``detect_chat`` must read :meth:`recent_chat`
        rather than polling the API itself.
        """
        task = self._listeners.get(channel)
        return task is not None and not task.done()

    def record_recent_chat(self, channel: str, **info: Any) -> None:
        """Stash the latest inbound chat seen on ``channel`` (called by the
        listeners). Stamped with a wall-clock time so stale records expire."""
        import time

        self._recent_chats[channel] = {**info, "at": time.time()}

    def recent_chat(self, channel: str, max_age_s: float = 3600.0) -> dict[str, Any] | None:
        """The most recent inbound chat on ``channel``, or None if there isn't
        one within ``max_age_s`` (default 1h) so a long-stale record can't be
        mistaken for a fresh "Start"."""
        import time

        rec = self._recent_chats.get(channel)
        if not rec:
            return None
        if max_age_s and (time.time() - float(rec.get("at", 0))) > max_age_s:
            return None
        return rec

    async def stop(self) -> None:
        tasks = [*self._tasks, *self._listeners.values()]
        for t in tasks:
            if not t.done():
                t.cancel()
        for t in tasks:
            try:
                await t
            except BaseException:  # noqa: BLE001 — cancellation / already-logged
                pass
        self._tasks.clear()
        self._listeners.clear()

    # ----- in-loop hooks --------------------------------------------------

    def enqueue_escalation(self, payload: dict[str, Any]) -> bool:
        """Non-blocking hand-off from the EscalationSource. Returns acceptance."""
        try:
            self._queue.put_nowait(payload)
            return True
        except asyncio.QueueFull:
            logger.warning("[sentinel] escalation queue full; dropping")
            return False

    def has_attached_ui(self, session_id: str) -> bool:
        session = self._get_live_session(session_id)
        return bool(session is not None and getattr(session, "sse_client_count", 0) > 0)

    async def on_local_resume(self, session_id: str) -> None:
        """A reply arrived in-app — close any open escalation for this session,
        on the runtime side AND (cross-channel) the backend Hive Inbox row, so a
        colony answered in-app doesn't linger as a stale "needs you"."""
        had_hive = False
        for rec in store.list_all_open():
            if rec.session_id == session_id:
                if rec.channel == notifier.CHANNEL_HIVE:
                    had_hive = True
                store.resolve_escalation(rec.colony_id, rec.escalation_id, resolved_by="local")
                self._by_token.pop(rec.correlation_token, None)
        # Only hit the backend when a Hive escalation was actually open.
        if had_hive:
            try:
                await notifier.resolve_hive_session(session_id, resolved_by="local")
            except Exception:
                logger.debug("sentinel: hive backend resolve failed", exc_info=True)

    # ----- outbound delivery ----------------------------------------------

    async def _drain_escalations(self) -> None:
        while True:
            payload = await self._queue.get()
            try:
                await self._handle_escalation(payload)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("[sentinel] escalation delivery failed", exc_info=True)
            finally:
                self._queue.task_done()

    async def _handle_escalation(self, payload: dict[str, Any]) -> None:
        channel = payload.get("channel")
        target = payload.get("target") or {}
        if not channel or not target:
            logger.warning("[sentinel] escalation has no channel/target; dropping (colony=%s)", payload.get("colony_id"))
            return

        colony_id = payload["colony_id"]
        thread = payload.get("thread") or {}
        send_under = self._thread_ref_for(channel, thread)

        # Hive renders title + body in its own UI, so it gets the raw detail as
        # the body plus structured routing meta. Telegram/Slack get one
        # mrkdwn-formatted blob.
        meta = None
        if channel == notifier.CHANNEL_HIVE:
            from framework.sentinel import runtime_identity

            text = payload.get("question_text") or "(the queen stalled with no message)"
            meta = {
                "runtime_id": runtime_identity.get_runtime_id(),
                "runtime_kind": runtime_identity.get_runtime_kind(),
                "session_id": payload["session_id"],
                "colony_id": colony_id,
                "kind": payload.get("kind", "blocker"),
                "title": self._hive_title(payload),
                "correlation_token": payload["correlation_token"],
                "deep_link": None,
            }
        else:
            text = self._format_message(payload)

        result = await notifier.send(channel, target, text, send_under, meta=meta)

        anchor = self._reply_anchor(channel, result.message_id) if result.ok else {}
        rec = store.EscalationRecord(
            escalation_id=payload["escalation_id"],
            colony_id=colony_id,
            session_id=payload["session_id"],
            correlation_token=payload["correlation_token"],
            park_reason=payload.get("park_reason", ""),
            question_text=payload.get("question_text", ""),
            channel=channel,
            thread_ref=anchor,
        )
        # One open Sentinel item per session: the latest report supersedes any
        # prior open one (e.g. stale progress), so the inbox is a live status
        # rather than a pile of "open" rows. A blocker holds the source, so it's
        # never superseded by a later report while still awaiting a reply.
        for prev in store.list_open(colony_id):
            if prev.session_id == rec.session_id and prev.escalation_id != rec.escalation_id:
                store.resolve_escalation(prev.colony_id, prev.escalation_id, resolved_by="superseded")
                self._by_token.pop(prev.correlation_token, None)
        store.write_escalation(rec)
        self._by_token[rec.correlation_token] = (rec.colony_id, rec.escalation_id)

        if not result.ok:
            logger.warning("[sentinel] message not delivered (colony=%s): %s", colony_id, result.error)
            return
        # First escalation for this colony becomes the thread root for grouping.
        if not thread and anchor:
            store.update_notifications_thread(colony_id, anchor)

    def _format_message(self, payload: dict[str, Any]) -> str:
        # The (ref:) correlation token is intentionally NOT shown: replies are
        # matched by thread + the single-open-per-colony invariant (see
        # _resolve_record), so the user never needs to see or type it. The
        # parsing path stays intact for any reply that does quote it.
        colony = payload["colony_id"]
        detail = _to_mrkdwn(payload.get("question_text") or "(no detail)")
        kind = payload.get("kind")
        # done/progress are FYI reports (no answer required); heartbeat is a
        # redirectable checkpoint; blocker (default) is the only "needs you".
        if kind == "done":
            return f'✅ Your colony "{colony}" finished.\n\n{detail}\n\nReply to send it back out, or ignore.'
        if kind == "progress":
            return f'🐝 Your colony "{colony}" — progress update:\n\n{detail}\n\nReply to redirect it, or ignore to let it keep going.'
        if kind == "heartbeat":
            return (
                f'🐝 Your colony "{colony}" is still working.\n\n'
                f"It's been running on its own for a while — latest checkpoint:\n\n"
                f"{detail}\n\n"
                f"Reply to redirect it, or ignore to let it keep going."
            )
        return f'🐝 Your colony "{colony}" needs you.\n\n{detail}\n\nReply to this message to answer and resume the colony.'

    @staticmethod
    def _hive_title(payload: dict[str, Any]) -> str:
        """Short headline for the Hive Inbox row (body carries the detail)."""
        colony = payload["colony_id"]
        kind = payload.get("kind")
        if kind == "done":
            return f'Colony "{colony}" finished'
        if kind == "progress":
            return f'Colony "{colony}" — progress'
        if kind == "heartbeat":
            return f'Colony "{colony}" is still working'
        return f'Colony "{colony}" needs you'

    @staticmethod
    def _thread_ref_for(channel: str, thread: dict[str, Any]) -> dict[str, Any] | None:
        """How to post UNDER the colony's existing thread root, or None."""
        if channel == notifier.CHANNEL_TELEGRAM and thread.get("message_id"):
            return {"message_id": thread["message_id"]}
        if channel == notifier.CHANNEL_SLACK and thread.get("ts"):
            return {"ts": thread["ts"]}
        return None

    @staticmethod
    def _reply_anchor(channel: str, message_id: str | None) -> dict[str, Any]:
        """The anchor we store so a reply threads/matches back."""
        if not message_id:
            return {}
        if channel == notifier.CHANNEL_TELEGRAM:
            return {"message_id": int(message_id) if str(message_id).isdigit() else message_id}
        if channel == notifier.CHANNEL_HIVE:
            # Hive replies resolve by correlation token, not by a thread anchor.
            return {}
        return {"ts": message_id}

    # ----- inbound routing + resume ---------------------------------------

    async def on_inbound(
        self,
        channel: str,
        sender_id: str,
        text: str,
        thread_ref: dict[str, Any] | None = None,
        source: str | None = None,
    ) -> None:
        rec = self._resolve_record(channel, text, thread_ref)
        if rec is None or rec.status != store.STATUS_OPEN:
            return

        # Sender authentication — strict per-colony allowlist.
        cfg = store.load_notifications_config(rec.colony_id)
        if cfg.allowlist and str(sender_id) not in cfg.allowlist:
            logger.warning("[sentinel] reply from unauthorized sender %s (colony=%s)", sender_id, rec.colony_id)
            return

        reply = token.strip_ref(text)
        resumed = await self._resume(rec, reply)
        if resumed:
            store.resolve_escalation(rec.colony_id, rec.escalation_id, resolved_by=str(sender_id))
            self._by_token.pop(rec.correlation_token, None)
            logger.info("[sentinel] resumed colony=%s from reply", rec.colony_id)

    def _resolve_record(self, channel: str, text: str, thread_ref: dict[str, Any] | None) -> store.EscalationRecord | None:
        # Primary: the (ref: …) token.
        tok = token.extract_token(text)
        if tok and tok in self._by_token:
            colony_id, esc_id = self._by_token[tok]
            rec = store.load_escalation(colony_id, esc_id)
            if rec is not None and token.verify_token(tok, rec.escalation_id):
                return rec
        # Fallback: a unique open escalation on this channel (threaded reply
        # without a quoted token). Token is required when ambiguous.
        candidates = [r for r in store.list_all_open() if r.channel == channel]
        if len(candidates) == 1:
            return candidates[0]
        if thread_ref:
            matched = [r for r in candidates if self._thread_matches(r, thread_ref)]
            if len(matched) == 1:
                return matched[0]
        return None

    @staticmethod
    def _thread_matches(rec: store.EscalationRecord, thread_ref: dict[str, Any]) -> bool:
        anchor = rec.thread_ref or {}
        if "message_id" in thread_ref and "message_id" in anchor:
            return str(thread_ref["message_id"]) == str(anchor["message_id"])
        if "ts" in thread_ref and "ts" in anchor:
            return str(thread_ref["ts"]) == str(anchor["ts"])
        return False

    async def _resume(self, rec: store.EscalationRecord, reply: str) -> bool:
        session = self._get_live_session(rec.session_id)
        if session is None:
            session = await self._cold_restore(rec)
        if session is None:
            logger.warning("[sentinel] could not reach session %s to resume", rec.session_id)
            return False
        executor = getattr(session, "queen_executor", None)
        node = executor.node_registry.get("queen") if executor is not None else None
        if node is None or not hasattr(node, "inject_event"):
            logger.warning("[sentinel] no queen node for session %s", rec.session_id)
            return False
        await node.inject_event(reply, is_client_input=True)
        return True

    async def _cold_restore(self, rec: store.EscalationRecord) -> Any | None:
        try:
            return await self._session_manager.create_session(
                colony_id=rec.colony_id,
                queen_resume_from=rec.session_id,
            )
        except Exception:
            logger.warning("[sentinel] cold-restore failed for %s", rec.session_id, exc_info=True)
            return None

    def _get_live_session(self, session_id: str) -> Any | None:
        sm = self._session_manager
        getter = getattr(sm, "get_live_session", None)
        if callable(getter):
            return getter(session_id)
        # Fallback to the internal map if the accessor isn't present.
        return getattr(sm, "_sessions", {}).get(session_id)
