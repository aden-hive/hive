"""Queens writing to each other.

A queen writes to another with ``message_queen`` (:mod:`framework.tools.queen_mail_tools`). Each
writer has one session of her own with the queen she writes to, kept across letters and restarts:
a channel session (channel ``"queens"``) whose meta.json names the writer (``peer``) and the
session her latest letter came from (``reply_to``). A letter arrives there as
``[Name(queen_id)]: text``, the way a chat app's message does, so memory and soul credit the
writer. What the queen says in that session goes back the same way, and wakes the writer: to the
session of the letter her turn answers, or the writer's latest one. To go on, the writer writes again.

A queen run by Claude Code (``queen_mail.claude_code``) takes part the same way, with Claude Code
conversations where a Hive queen has sessions (:mod:`framework.server.claude_code_queens`). She
writes through two routes here, ``/api/queen-mail/...``, with a token good for one conversation of
hers.

A letter or reply is one hop further down the chain of the deepest letter or reply that has entered
the conversation it comes from since anyone else (a person, a chat app) last spoke there; a timer
or a worker's report starts a new chain. A chain stops at ``queen_mail.max_depth`` hops, and a queen
sends at most ``daily_limit`` letters a day. Every hop is a line of ``queens/mail.jsonl``: who, to
whom, which sessions, what set it off and how deep, never the text (the sessions keep it).
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import hmac
import json
import logging
import secrets
import uuid
import weakref
from collections import OrderedDict
from datetime import datetime
from typing import TYPE_CHECKING, Any

from aiohttp import web

from framework.server.channels import ChannelError, ChannelHost, QueenOutput, _merge_meta, _newest_successor, _read_meta
from framework.server.claude_code_queens import ClaudeCodeQueens, is_conversation_ref

if TYPE_CHECKING:
    from framework.server.session_manager import Session, SessionManager

logger = logging.getLogger(__name__)

#: The channel name that marks a queen's sessions with her correspondents.
CHANNEL = "queens"
LOG_FILE = "mail.jsonl"
TOKEN_HEADER = "X-Queen-Mail-Token"
# Letters whose return address is remembered (a reply goes back where the letter it answers came from).
_LETTERS_KEPT = 2000


class QueenMailError(Exception):
    """A letter that can't be sent; the message says why, to the queen who tried."""


class QueenMail:
    """Letters between queens, in one server. Lives on ``SessionManager.queen_mail``."""

    def __init__(self, manager: SessionManager) -> None:
        self._manager = manager
        self._host = ChannelHost(CHANNEL, manager, {})
        self._locks: dict[str, asyncio.Lock] = {}
        # Per session, from the inputs that entered its conversation since anyone else last spoke
        # there: the newest letter or reply (what her next words answer) and the deepest hop.
        self._answering: dict[str, str] = {}
        self._depth: dict[str, int] = {}
        # Our deliveries not yet in their conversation: correlation id -> (session id, hop, depth).
        self._pending: dict[str, tuple[str, str, int]] = {}
        self._watched: dict[str, weakref.ref[Any]] = {}
        # Sessions of Hive queens with their correspondents whose words we take back.
        self._subscribed: set[str] = set()
        # Where each recent letter came from, by hop id.
        self._letters: OrderedDict[str, str] = OrderedDict()
        # The latest return address of each (queen, writer) thread.
        self._routes: dict[tuple[str, str], str] = {}
        self._day = ""
        self._sent: dict[str, int] = {}
        self._secret = secrets.token_bytes(32)
        self.claude_code = ClaudeCodeQueens(self)
        #: Where a Claude Code queen's runs reach this server; set by ``hive serve`` once it listens.
        self.base_url: str | None = None
        self._closed = False
        self._remove_listener = manager.add_session_listener(self._on_session_live)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._remove_listener()
        self._host.close()
        self.claude_code.close()

    def token_for(self, ref: str) -> str:
        """The token that lets a Claude Code run write from conversation ``ref``, and from it alone."""
        return hmac.new(self._secret, ref.encode("utf-8"), hashlib.sha256).hexdigest()

    def authorizes(self, ref: str, token: str) -> bool:
        return bool(ref) and hmac.compare_digest(token, self.token_for(ref))

    def correspondents(self, queen_id: str | None) -> list[dict[str, str]]:
        """The queens ``queen_id`` may write to: every queen taking part but her."""
        from framework.agents.queen.queen_profiles import list_queens
        from framework.config import get_queen_mail_config

        config = get_queen_mail_config()
        if not config.enabled:
            return []
        hive = [
            {"id": q["id"], "name": q.get("name") or q["id"], "title": q.get("title") or ""}
            for q in list_queens()
            if q["id"] != queen_id and q["id"] not in config.claude_code and config.includes(q["id"])
        ]
        claude = [{"id": c.queen_id, "name": c.name, "title": c.title} for c in config.claude_code.values() if c.queen_id != queen_id]
        return hive + claude

    async def send(self, session: Session, to_queen: str, text: str) -> dict[str, Any]:
        """Hand ``text`` from the queen of ``session`` to ``to_queen``."""
        return await self._send(session.queen_name, session.id, to_queen, text, self._cause_of(session.id))

    async def send_from_conversation(self, ref: str, to_queen: str, text: str) -> dict[str, Any]:
        """Hand ``text`` from a Claude Code queen's conversation ``ref`` to ``to_queen``."""
        writer = self.claude_code.queen_of(ref)
        if writer is None:
            raise QueenMailError("This conversation isn't known to Hive")
        return await self._send(writer, ref, to_queen, text, self.claude_code.cause_of(ref))

    def name_of(self, queen_id: str) -> str:
        """``queen_id``'s name, as letters and replies show it."""
        from framework.agents.queen.queen_profiles import load_queen_profile
        from framework.config import get_queen_mail_config

        claude = get_queen_mail_config().claude_code.get(queen_id)
        if claude is not None:
            return claude.name
        try:
            return str(load_queen_profile(queen_id).get("name") or queen_id)
        except FileNotFoundError:
            return queen_id

    async def deliver_reply(self, queen: str, writer: str, reply_to: str | None, text: str, cause: tuple[str, int] | None, from_ref: str) -> None:
        """Take ``text``, what ``queen`` said in her conversation ``from_ref`` with ``writer``, to ``reply_to``.

        ``cause`` is the hop (id, depth) that set off what she said.
        """
        from framework.config import get_queen_mail_config
        from framework.server.routes_execution import QueenUnavailableError, deliver_to_queen

        caused_by, depth = (cause[0], cause[1] + 1) if cause else (None, 1)
        config = get_queen_mail_config()

        def dropped(reason: str, to_ref: str | None = reply_to) -> None:
            logger.info("queen mail: %s's reply to %s not delivered (%s)", queen, writer, reason)
            self._log("reply", queen, writer, from_ref, to_ref or "", caused_by, depth, len(text), dropped=reason)

        if depth > config.max_depth:
            dropped("max_depth")
            return
        if not (config.includes(queen) and config.includes(writer)):
            dropped("off")
            return
        if not reply_to:
            dropped("unreachable")
            return
        name = self.name_of(queen)
        hop = _hop_id()
        if is_conversation_ref(reply_to):
            if not self.claude_code.reply(reply_to, _reply_letter(name, queen, text), hop, depth):
                dropped("unreachable")
                return
            self._log("reply", queen, writer, from_ref, reply_to, caused_by, depth, len(text), hop=hop)
            return
        session = await self._reachable(writer, reply_to)
        if session is None:
            dropped("unreachable")
            return
        correlation = self._expect(session, hop, depth)
        session.fork_kickoff_pending = False
        try:
            await deliver_to_queen(
                self._manager, session, _reply_letter(name, queen, text), display_message=_said(name, queen, text), correlation_id=correlation
            )
        except QueenUnavailableError:
            self._pending.pop(correlation, None)
            dropped("unavailable", session.id)
            return
        self._log("reply", queen, writer, from_ref, session.id, caused_by, depth, len(text), hop=hop)

    # ------------------------------------------------------------------

    async def _send(self, writer: str | None, from_ref: str, to_queen: str, text: str, cause: tuple[str, int] | None) -> dict[str, Any]:
        from framework.config import get_queen_mail_config

        config = get_queen_mail_config()
        text = text.strip()
        taking_part = {q["id"] for q in self.correspondents(None)}
        if not writer or writer not in taking_part:
            raise QueenMailError("You don't take part in queen mail (queen_mail in configuration.json)")
        if not text:
            raise QueenMailError("The message is empty")
        if to_queen == writer:
            raise QueenMailError("That's your own id")
        if to_queen not in taking_part:
            raise QueenMailError(f"There's no queen {to_queen!r} to write to; list_queens names them")
        caused_by, depth = (cause[0], cause[1] + 1) if cause else (None, 1)
        if depth > config.max_depth:
            raise QueenMailError(
                f"This chain of letters already has {config.max_depth} hops, the most queen_mail.max_depth allows. "
                "It starts again when someone else writes to you."
            )
        if not self._reserve(writer, config.daily_limit):
            raise QueenMailError(f"You've sent {config.daily_limit} letters today, the most queen_mail.daily_limit allows")

        name = self.name_of(writer)
        hop = _hop_id()
        self._remember_letter(hop, from_ref)
        self._routes[(to_queen, writer)] = from_ref
        try:
            if to_queen in config.claude_code:
                to_ref = self.claude_code.letter(to_queen, writer, from_ref, _letter(name, writer, text), hop, depth)
            else:
                to_ref = await self._send_to_hive_queen(writer, from_ref, to_queen, name, text, hop, depth)
        except BaseException:
            self._release(writer)
            raise
        self._log("message", writer, to_queen, from_ref, to_ref, caused_by, depth, len(text), hop=hop)
        return {"sent": hop, "to": to_queen, "depth": depth}

    async def _send_to_hive_queen(self, writer: str, from_ref: str, to_queen: str, name: str, text: str, hop: str, depth: int) -> str:
        """Hand the letter to ``to_queen``'s session with ``writer``; returns that session's id."""
        # One writer's letters to one queen go in one at a time, so two first letters open one session.
        async with self._locks.setdefault(f"thread:{to_queen}:{writer}", asyncio.Lock()):
            try:
                sid = await self._host.open_session(to_queen, session_id=self._thread_of(to_queen, writer), title=name)
                target = self._manager.get_session(sid)
                if target is None:
                    raise QueenMailError(f"{to_queen} can't take letters now")
                if target.queen_dir is not None:
                    _merge_meta(target.queen_dir, peer=writer, reply_to=from_ref)
                self._subscribe(sid, to_queen, writer)
                correlation = self._expect(target, hop, depth)
                try:
                    return await self._host.send(sid, _letter(name, writer, text), display_text=_said(name, writer, text), correlation_id=correlation)
                except BaseException:
                    self._pending.pop(correlation, None)
                    raise
            except ChannelError as e:
                raise QueenMailError(f"{to_queen} can't take letters now: {e}") from e

    def _subscribe(self, session_id: str, queen: str, writer: str) -> None:
        """Take what ``queen`` says in her session with ``writer`` back to the writer, from now on."""
        if session_id in self._subscribed:
            return
        self._subscribed.add(session_id)
        self._host.subscribe(session_id, functools.partial(self._reply, queen, writer))

    async def _reply(self, queen: str, writer: str, output: QueenOutput) -> None:
        """Take what Hive queen ``queen`` said in her session with ``writer`` back to the writer."""
        text = _reply_text(output)
        if not text:
            return
        sid = output.session_id
        self._subscribed.add(sid)  # the conversation may have moved on to this session
        cause = self._cause_of(sid)
        reply_to = (self._letters.get(cause[0]) if cause else None) or self._routes.get((queen, writer)) or self._meta_of(sid).get("reply_to")
        await self.deliver_reply(queen, writer, reply_to, text, cause, sid)

    async def _reachable(self, queen_id: str, session_id: str) -> Session | None:
        """``session_id`` (or the session it moved on to), live, unless it is gone or locked."""
        from framework.server.routes_queens import _create_bound_queen_session
        from framework.server.session_manager import _find_queen_session_dir

        session_dir = _find_queen_session_dir(session_id)
        if session_dir.is_dir():
            session_id = _newest_successor(session_dir.parent, session_id)
        async with self._locks.setdefault(session_id, asyncio.Lock()):
            session = self._manager.get_session(session_id)
            if session is None:
                if not _find_queen_session_dir(session_id).is_dir():
                    return None
                try:
                    session = await _create_bound_queen_session(self._manager, queen_id, resume_from=session_id)
                except Exception:
                    logger.warning("queen mail: couldn't resume session %s", session_id, exc_info=True)
                    return None
        # A session that spawned a colony is locked; the conversation went on in the colony.
        return None if session.colony_spawned else session

    def _thread_of(self, queen_id: str, writer: str) -> str | None:
        """The session ``writer`` already has with ``queen_id`` (her newest), if any."""
        from framework.config import queen_sessions_dir

        sessions = queen_sessions_dir(queen_id)
        if not sessions.is_dir():
            return None
        for session_dir in sorted((d for d in sessions.iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True):
            meta = _read_meta(session_dir)
            if meta.get("channel") == CHANNEL and meta.get("peer") == writer:
                return session_dir.name
        return None

    @staticmethod
    def _meta_of(session_id: str) -> dict[str, Any]:
        from framework.server.session_manager import _find_queen_session_dir

        return _read_meta(_find_queen_session_dir(session_id))

    # --- causes ----------------------------------------------------------

    def _expect(self, session: Session, hop: str, depth: int) -> str:
        """Note that ``hop`` is being handed to ``session``; returns the correlation id to hand it with."""
        self._watch(session)
        correlation = uuid.uuid4().hex
        self._pending[correlation] = (session.id, hop, depth)
        return correlation

    def _cause_of(self, session_id: str) -> tuple[str, int] | None:
        """(the hop her next words answer, the depth of the chain they continue), if a letter or reply set them off."""
        if session_id not in self._depth:
            return None
        return self._answering[session_id], self._depth[session_id]

    def _watch(self, session: Session) -> None:
        """Follow what enters ``session``'s conversation, to know what her words answer."""
        from framework.host.event_bus import EventType

        bus = session.event_bus
        watched = self._watched.get(session.id)
        if watched is not None and watched() is bus:
            return
        self._watched[session.id] = weakref.ref(bus)
        sid = session.id

        async def on_event(event: Any) -> None:
            if event.type == EventType.SESSION_FORKED:
                new_id = (event.data or {}).get("new_session_id")
                if isinstance(new_id, str) and sid in self._depth:
                    self._answering[new_id], self._depth[new_id] = self._answering[sid], self._depth[sid]
                return
            if event.type == EventType.CLIENT_INPUT_COMMITTED and event.stream_id != "queen":
                return
            ours = self._pending.pop(event.correlation_id, None) if event.type == EventType.CLIENT_INPUT_COMMITTED else None
            if ours is not None and ours[0] == sid:
                _, hop, depth = ours
                self._answering[sid] = hop
                self._depth[sid] = max(depth, self._depth.get(sid, 0))
            else:
                # Someone else spoke, a timer fired or a worker reported: a new chain starts here.
                self._answering.pop(sid, None)
                self._depth.pop(sid, None)

        bus.subscribe(
            event_types=[EventType.CLIENT_INPUT_COMMITTED, EventType.TRIGGER_FIRED, EventType.SUBAGENT_REPORT, EventType.SESSION_FORKED],
            handler=on_event,
        )

    def _on_session_live(self, session: Session) -> None:
        """A session that comes live (resumed, after a restart too) keeps its causes and its route back."""
        if session.id in self._depth:
            self._watch(session)
        if session.id in self._subscribed:
            return
        meta = self._meta_of(session.id)
        if meta.get("channel") == CHANNEL and isinstance(meta.get("peer"), str) and isinstance(meta.get("queen_id"), str):
            self._subscribe(session.id, meta["queen_id"], meta["peer"])

    def _remember_letter(self, hop: str, from_ref: str) -> None:
        self._letters[hop] = from_ref
        while len(self._letters) > _LETTERS_KEPT:
            self._letters.popitem(last=False)

    # --- the daily limit and the log ---------------------------------------

    def _reserve(self, queen_id: str, limit: int) -> bool:
        """Count a letter of ``queen_id``'s against today's limit, if it has room."""
        today = _now().date().isoformat()
        if today != self._day:
            self._day = today
            self._sent = {}
            for record in _read_log():
                if record.get("kind") == "message" and not record.get("dropped") and str(record.get("at", "")).startswith(today):
                    self._sent[record["from"]] = self._sent.get(record["from"], 0) + 1
        if self._sent.get(queen_id, 0) >= limit:
            return False
        self._sent[queen_id] = self._sent.get(queen_id, 0) + 1
        return True

    def _release(self, queen_id: str) -> None:
        self._sent[queen_id] = max(0, self._sent.get(queen_id, 0) - 1)

    def _log(
        self,
        kind: str,
        sender: str,
        recipient: str,
        from_session: str,
        to_session: str,
        caused_by: str | None,
        depth: int,
        chars: int,
        *,
        hop: str | None = None,
        dropped: str | None = None,
    ) -> None:
        from framework.agents.queen import queen_profiles

        record: dict[str, Any] = {
            "id": hop or _hop_id(),
            "at": _now().isoformat(timespec="seconds"),
            "kind": kind,
            "from": sender,
            "to": recipient,
            "from_session": from_session,
            "to_session": to_session,
            "caused_by": caused_by,
            "depth": depth,
            "chars": chars,
        }
        if dropped:
            record["dropped"] = dropped
        path = queen_profiles.QUEENS_DIR / LOG_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read_log() -> list[dict[str, Any]]:
    from framework.agents.queen import queen_profiles

    path = queen_profiles.QUEENS_DIR / LOG_FILE
    if not path.is_file():
        return []
    records = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def _now() -> datetime:
    return datetime.now().astimezone()


def _hop_id() -> str:
    return "hop_" + uuid.uuid4().hex[:12]


def _said(name: str, queen_id: str, text: str) -> str:
    """How a queen's words appear to the other: the "[nick(id)]: text" a chat app's message has.

    A "[...]:" inside the text is broken up, so the words can't be credited to someone else.
    """
    return f"[{name}({queen_id})]: {text.replace(']:', '] :')}"


def _letter(name: str, queen_id: str, text: str) -> str:
    return (
        f"(A letter from {name}, another queen, sent with message_queen. What you say in this conversation "
        "goes back to her, so just answer here; you don't need message_queen to reply.)\n" + _said(name, queen_id, text)
    )


def _reply_letter(name: str, queen_id: str, text: str) -> str:
    return f"(A reply from {name} to your message_queen letter. To go on, write to her again.)\n" + _said(name, queen_id, text)


def _reply_text(output: QueenOutput) -> str:
    """What the writer is told of one thing the queen she wrote to said."""
    if output.kind == "message":
        return output.text.strip()
    if output.kind == "error":
        return f"(Her reply failed: {output.text.strip()})"
    if output.kind == "question":
        asked = []
        for question in output.questions:
            options = question.get("options")
            choices = f" ({' / '.join(map(str, options))})" if isinstance(options, list) and options else ""
            asked.append(f"{question.get('prompt', '')}{choices}")
        return "(She asks:) " + "\n".join(asked)
    if output.kind == "files":
        return "(She attached: " + ", ".join(str(path) for path in output.files) + ")"
    return ""


# ----------------------------------------------------------------------
# Routes for a Claude Code queen's runs (framework.server.queen_mail_mcp)
# ----------------------------------------------------------------------


def _mail_for(request: web.Request, ref: str) -> QueenMail | None:
    """The server's queen mail, when the request carries the token of conversation ``ref``."""
    mail = request.app["manager"].queen_mail
    if mail is None or not mail.authorizes(ref, request.headers.get(TOKEN_HEADER, "")):
        return None
    return mail


async def handle_queens(request: web.Request) -> web.Response:
    """GET /api/queen-mail/queens?from=<conversation> -- the queens that conversation's queen may write to."""
    ref = request.query.get("from", "")
    mail = _mail_for(request, ref)
    if mail is None:
        return web.json_response({"error": "unauthorized"}, status=401)
    queen = mail.claude_code.queen_of(ref)
    if queen is None:
        return web.json_response({"error": "This conversation isn't known to Hive"}, status=404)
    return web.json_response({"queens": mail.correspondents(queen)})


async def handle_letter(request: web.Request) -> web.Response:
    """POST /api/queen-mail/letters {from, to, message} -- a letter from a Claude Code queen's conversation."""
    try:
        body = await request.json()
    except ValueError:
        return web.json_response({"error": "The body isn't JSON"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "The body must be a JSON object"}, status=400)
    ref = str(body.get("from") or "")
    mail = _mail_for(request, ref)
    if mail is None:
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        sent = await mail.send_from_conversation(ref, str(body.get("to") or ""), str(body.get("message") or ""))
    except QueenMailError as e:
        return web.json_response({"error": str(e)}, status=400)
    return web.json_response(sent)


def register_routes(app: web.Application) -> None:
    app.router.add_get("/api/queen-mail/queens", handle_queens)
    app.router.add_post("/api/queen-mail/letters", handle_letter)
