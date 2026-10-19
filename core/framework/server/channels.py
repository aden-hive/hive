"""Channels: chat apps that reach queens from outside the dashboard.

A channel is a package installed next to Hive that names a factory in the ``hive.channels``
entry-point group::

    [project.entry-points."hive.channels"]
    mychat = "mychat:MyChatChannel"

``hive serve`` calls the factory with a :class:`ChannelHost` and starts what it returns when the
channel's section of ``configuration.json`` enables it::

    {"channels": {"mychat": {"enabled": true}}}

A channel that fails to load or start is logged and left out; it never takes the server down.

Each conversation a channel carries (a group chat, a private chat) is a queen session: the
channel opens it, sends the user's messages into it, and hears the queen through
:meth:`ChannelHost.subscribe`. Everything the queen says in that session reaches the channel,
including replies to messages typed in the dashboard. Channel sessions are left alone when the
dashboard opens or starts a chat with the same queen.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import io
import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from aiohttp import web

    from framework.server.session_manager import Session, SessionManager

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "hive.channels"
# A channel's start() should hand its work to background tasks and return.
_START_TIMEOUT_S = 30.0


@runtime_checkable
class Channel(Protocol):
    """What a channel factory returns."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


@dataclass(frozen=True)
class QueenOutput:
    """Something the queen said in a channel's session.

    ``kind`` is one of:

    - ``"message"``: the text of one finished model turn. A queen often says several in a row,
      between tool calls.
    - ``"question"``: she asked the user something. ``questions`` is the ``ask_user`` list of
      ``{"id", "prompt", "options"?}`` (``options`` only on multiple-choice questions); the next
      message sent to the session answers it. The question is not also sent as a message.
    - ``"error"``: a model call failed. ``text`` is the error the dashboard shows. She waits for
      the next message.
    - ``"files"``: she handed the user files with ``attach_file`` (an image she made, a report).
      ``files`` are their copies in the session's ``data/attachments``; the dashboard shows the
      same files on her next message.

    ``session_id`` is the session she said it in. When she moves the conversation into a new
    session, outputs carry the new id: keep it for the next :meth:`ChannelHost.send`.
    """

    session_id: str
    kind: Literal["message", "question", "error", "files"]
    text: str = ""
    questions: list[dict[str, Any]] = field(default_factory=list)
    files: list[Path] = field(default_factory=list)


OutputHandler = Callable[[QueenOutput], Awaitable[None]]


class ChannelError(RuntimeError):
    """A queen session can't take a channel's message: no such queen, a session locked by a
    colony it spawned, or a queen that can't be started."""


class ChannelHost:
    """What Hive gives one channel: its settings, a directory for its state, and queen sessions."""

    def __init__(self, name: str, manager: SessionManager, config: dict[str, Any]) -> None:
        self.name = name
        #: The channel's section of ``configuration.json`` (``channels.<name>``).
        self.config = config
        self._manager = manager
        self._subs: dict[str, _Subscription] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._remove_listener = manager.add_session_listener(self._on_session_live)

    @property
    def state_dir(self) -> Path:
        """``$HIVE_HOME/channels/<name>``: where the channel keeps its own files."""
        from framework.config import HIVE_HOME

        path = HIVE_HOME / "channels" / self.name
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def judge(self, question: str, state: dict[str, Any], *, criteria: dict[str, str] | None = None) -> float | None:
        """The probability, from the judge in the ``judge`` slot, that the answer to ``question`` is yes.

        ``state`` is what the judge reads; ``criteria`` may describe what counts as ``"true"`` and
        ``"false"``. ``None`` when no judge is configured or it can't answer now (the reason is
        logged). Each call is one request to the judge's vendor.
        """
        from framework.server import judge

        return await judge.ask(question, state, criteria=criteria)

    async def open_session(self, queen_id: str, *, session_id: str | None = None, title: str | None = None) -> str:
        """The session for one conversation with ``queen_id``, started and ready for :meth:`send`.

        ``session_id`` is the one this conversation used before. It is resumed (or its newest
        successor, if the queen moved the conversation on). Without one, or when it is gone or
        locked, a new session is started and named ``title``. Returns the session's id.
        """
        from framework.agents.queen.queen_profiles import ensure_default_queens, load_queen_profile

        ensure_default_queens()
        try:
            load_queen_profile(queen_id)
        except FileNotFoundError as e:
            raise ChannelError(f"No queen {queen_id!r}: check the queen id in the {self.name!r} channel's settings") from e

        if session_id:
            session = await self._resume(queen_id, session_id)
            if session is not None and not session.colony_spawned:
                self._follow(session_id, session.id)
                return session.id

        session = await self._manager.create_session(queen_name=queen_id, initial_phase="independent")
        self._claim(session)
        if title and session.queen_dir is not None:
            from framework.server.session_titles import write_title

            write_title(session.queen_dir, title, source="user")
        return session.id

    async def send(self, session_id: str, text: str, *, images: Sequence[bytes] = (), display_text: str | None = None) -> str:
        """Send a user message into a session, resuming it if it was stopped.

        ``images`` are image files' bytes; they are saved into the session like the
        dashboard's attachments. ``display_text`` is what the dashboard shows in place of
        ``text``, when the two differ. Returns the id of the session that got the message,
        which differs from ``session_id`` after the queen moved the conversation on.
        """
        from framework.server.routes_execution import QueenUnavailableError, deliver_to_queen, prepare_queen_input

        queen_id = self._queen_of(session_id)
        if queen_id is None:
            raise ChannelError(f"No session {session_id!r}")
        session = await self._resume(queen_id, session_id)
        if session is None:
            raise ChannelError(f"Session {session_id!r} can't be resumed")
        if session.colony_spawned:
            raise ChannelError(f"Session {session.id!r} is locked because it spawned a colony; open a new one")
        self._follow(session_id, session.id)
        # A real message ends a fork's kickoff turn, as it does in /chat.
        session.fork_kickoff_pending = False

        blocks = [b for b in map(_image_block, images) if b is not None]
        message, blocks, saved = await prepare_queen_input(session, text, blocks or None)
        if not message and not blocks:
            raise ValueError("Nothing to send: the message has no text and no readable image")
        try:
            await deliver_to_queen(
                self._manager,
                session,
                message,
                image_content=blocks,
                display_message=display_text,
                saved_image_paths=saved,
            )
        except QueenUnavailableError as e:
            raise ChannelError(f"The queen of session {session.id!r} can't be started") from e
        return session.id

    def subscribe(self, session_id: str, handler: OutputHandler) -> None:
        """Call ``handler`` with what the queen says in ``session_id`` from now on.

        Calls come one at a time, in order, and keep coming after the session is stopped and
        resumed. A handler that raises is logged; later outputs still arrive. Subscribing
        again replaces the handler.
        """
        self.unsubscribe(session_id)
        sub = _Subscription(session_id, handler)
        self._subs[session_id] = sub
        live = self._manager.get_session(session_id)
        if live is not None:
            sub.attach(live, self._on_forked)

    def unsubscribe(self, session_id: str) -> None:
        """Stop hearing ``session_id``."""
        sub = self._subs.pop(session_id, None)
        if sub is not None:
            sub.close()

    def set_title(self, session_id: str, title: str) -> None:
        """Name a session in the dashboard; an empty title clears it.

        The queen's automatic title never replaces it.
        """
        from framework.server.session_manager import _find_queen_session_dir
        from framework.server.session_titles import write_title

        session_dir = _find_queen_session_dir(session_id)
        if not session_dir.is_dir():
            raise ChannelError(f"No session {session_id!r}")
        write_title(session_dir, title, source="user")

    def close(self) -> None:
        """Drop every subscription and stop watching sessions. Called after the channel stops."""
        self._remove_listener()
        for session_id in list(self._subs):
            self.unsubscribe(session_id)

    # ------------------------------------------------------------------

    def _queen_of(self, session_id: str) -> str | None:
        live = self._manager.get_session(session_id)
        if live is not None:
            return live.queen_name
        return self._manager._resume_queen_name(session_id)

    async def _resume(self, queen_id: str, session_id: str) -> Session | None:
        """The live session ``session_id`` (or its newest successor), resuming it from disk if
        needed; None when it is no DM session of ``queen_id``."""
        from framework.config import queen_sessions_dir
        from framework.server.routes_queens import _create_bound_queen_session

        session_id = _newest_successor(queen_sessions_dir(queen_id), session_id)
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            session = self._manager.get_session(session_id)
            if session is None:
                if not (queen_sessions_dir(queen_id) / session_id / "meta.json").is_file():
                    return None
                session = await _create_bound_queen_session(self._manager, queen_id, resume_from=session_id)
            if session.colony_id is not None or session.queen_name != queen_id:
                return None
            self._claim(session)
            return session

    def _claim(self, session: Session) -> None:
        """Mark ``session`` as this channel's, now and after a restart."""
        session.channel = self.name
        if session.queen_dir is not None:
            _merge_meta(session.queen_dir, channel=self.name)

    def _follow(self, old_id: str, new_id: str) -> None:
        """Keep hearing a conversation that moved from ``old_id`` to ``new_id``."""
        if old_id == new_id or old_id not in self._subs:
            return
        sub = self._subs.pop(old_id)
        sub.close()
        self.subscribe(new_id, sub.handler)

    def _on_forked(self, old_id: str, new_id: str) -> None:
        self._follow(old_id, new_id)

    def _on_session_live(self, session: Session) -> None:
        sub = self._subs.get(session.id)
        if sub is not None:
            session.channel = self.name
            sub.attach(session, self._on_forked)


class _Subscription:
    """Turns one session's event stream into :class:`QueenOutput` calls, in order."""

    def __init__(self, session_id: str, handler: OutputHandler) -> None:
        self.session_id = session_id
        self.handler = handler
        self._queue: asyncio.Queue[QueenOutput] = asyncio.Queue()
        self._worker = asyncio.create_task(self._deliver(), name=f"channel-output-{session_id}")
        self._bus: Any = None
        self._bus_subs: list[str] = []

    def attach(self, session: Session, on_forked: Callable[[str, str], None]) -> None:
        """Listen on ``session``'s event bus (a resumed session has a new one)."""
        from framework.agent_loop.visible_error import is_visible_error
        from framework.host.event_bus import EventType

        if session.event_bus is self._bus:
            return
        self._detach()
        pending = ""  # the text of the model turn in progress

        def reply_kind(text: str) -> Literal["message", "error"]:
            # A model gateway can return a failed call as an ordinary reply.
            return "error" if is_visible_error(text) else "message"

        async def on_event(event: Any) -> None:
            nonlocal pending
            if event.stream_id != "queen":
                return
            data = event.data or {}
            if event.type == EventType.CLIENT_OUTPUT_DELTA:
                pending = data.get("snapshot") or pending
            elif event.type == EventType.LLM_TURN_COMPLETE:
                if pending.strip():
                    self._put(reply_kind(pending), text=pending)
                pending = ""
            elif event.type == EventType.CLIENT_INPUT_REQUESTED:
                reason = data.get("park_reason")
                if reason == "ask_user" and data.get("questions"):
                    # A free-text question was streamed as text too; the question carries it.
                    self._put("question", questions=list(data["questions"]))
                elif reason == "llm_error" and pending.strip():
                    self._put("error", text=pending)
                elif pending.strip():
                    self._put(reply_kind(pending), text=pending)
                pending = ""
            elif event.type == EventType.SESSION_FORKED:
                new_id = data.get("new_session_id")
                if isinstance(new_id, str) and new_id:
                    on_forked(self.session_id, new_id)
            elif event.type == EventType.TOOL_CALL_COMPLETED:
                if data.get("tool_name") == "attach_file" and not data.get("is_error"):
                    files = _attached_files(data.get("result"))
                    if files:
                        self._put("files", files=files)

        self._bus = session.event_bus
        self._bus_subs = [
            session.event_bus.subscribe(
                event_types=[
                    EventType.CLIENT_OUTPUT_DELTA,
                    EventType.LLM_TURN_COMPLETE,
                    EventType.CLIENT_INPUT_REQUESTED,
                    EventType.SESSION_FORKED,
                    EventType.TOOL_CALL_COMPLETED,
                ],
                handler=on_event,
            )
        ]

    def close(self) -> None:
        self._detach()
        self._worker.cancel()

    def _detach(self) -> None:
        for sub_id in self._bus_subs:
            with contextlib.suppress(Exception):
                self._bus.unsubscribe(sub_id)
        self._bus, self._bus_subs = None, []

    def _put(self, kind: Literal["message", "question", "error", "files"], **fields: Any) -> None:
        self._queue.put_nowait(QueenOutput(session_id=self.session_id, kind=kind, **fields))

    async def _deliver(self) -> None:
        # Handlers do network I/O; calling them here instead of inside the bus's publish keeps a
        # slow chat app from stalling the queen.
        while True:
            output = await self._queue.get()
            try:
                await self.handler(output)
            except Exception:
                logger.exception("channel: handler failed for a %s in session %s", output.kind, output.session_id)


def _attached_files(result: Any) -> list[Path]:
    """The files an ``attach_file`` result published into the session.

    The result opens with a JSON summary (``{"attached": [{"resolved": ...}, ...]}``; Hive
    points ``resolved`` at the copy in ``data/attachments``), and may go on with the text of a
    text file it attached.
    """
    if not isinstance(result, str):
        return []
    try:
        summary, _ = json.JSONDecoder().raw_decode(result.lstrip())
    except ValueError:
        return []
    attached = summary.get("attached") if isinstance(summary, dict) else None
    paths = (Path(entry["resolved"]) for entry in attached or () if isinstance(entry, dict) and isinstance(entry.get("resolved"), str))
    return [path for path in paths if path.is_file()]


def _newest_successor(sessions_dir: Path, session_id: str) -> str:
    """Follow ``superseded_by`` from ``session_id`` to the session the conversation continues in."""
    seen = {session_id}
    while True:
        meta = _read_meta(sessions_dir / session_id)
        successor = meta.get("superseded_by")
        if not isinstance(successor, str) or successor in seen:
            return session_id
        seen.add(successor)
        session_id = successor


def _read_meta(session_dir: Path) -> dict[str, Any]:
    try:
        meta = json.loads((session_dir / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def _merge_meta(session_dir: Path, **fields: Any) -> None:
    meta = _read_meta(session_dir)
    if all(meta.get(k) == v for k, v in fields.items()):
        return
    meta.update(fields)
    tmp = session_dir / "meta.json.tmp"
    tmp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    tmp.replace(session_dir / "meta.json")


_PIL_MIMES = {"JPEG": "image/jpeg", "PNG": "image/png", "GIF": "image/gif", "WEBP": "image/webp"}
# Chat apps send camera photos at full size; a model reads one just as well at this size.
_MAX_IMAGE_SIDE = 2048
_MAX_IMAGE_BYTES = 2 * 1024 * 1024


def _image_block(data: bytes) -> dict[str, Any] | None:
    """An image file as the ``image_url`` block /chat takes. Big photos are scaled down to
    :data:`_MAX_IMAGE_SIDE` and sent as JPEG; formats a model can't take become PNG. None when
    ``data`` is not an image."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    try:
        with Image.open(io.BytesIO(data)) as im:
            mime = _PIL_MIMES.get(im.format or "")
            animated = getattr(im, "is_animated", False)
            if not animated and (max(im.size) > _MAX_IMAGE_SIDE or len(data) > _MAX_IMAGE_BYTES):
                small = ImageOps.exif_transpose(im).convert("RGB")
                small.thumbnail((_MAX_IMAGE_SIDE, _MAX_IMAGE_SIDE))
                out = io.BytesIO()
                small.save(out, format="JPEG", quality=85)
                data, mime = out.getvalue(), "image/jpeg"
            elif mime is None:
                out = io.BytesIO()
                im.convert("RGBA").save(out, format="PNG")
                data, mime = out.getvalue(), "image/png"
    except (UnidentifiedImageError, OSError):
        logger.warning("channel: skipped an attachment that is not an image (%d bytes)", len(data))
        return None
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}}


# ----------------------------------------------------------------------
# Running channels inside ``hive serve``
# ----------------------------------------------------------------------


@dataclass
class _Running:
    host: ChannelHost
    channel: Channel


def _installed() -> dict[str, Any]:
    from importlib.metadata import entry_points

    return {ep.name: ep for ep in entry_points(group=ENTRY_POINT_GROUP)}


async def start_channels(app: web.Application) -> None:
    """aiohttp on_startup hook: start each installed, enabled channel."""
    from framework.config import get_hive_config

    settings = get_hive_config().get("channels") or {}
    running: dict[str, _Running] = {}
    states: dict[str, dict[str, Any]] = {}
    for name, entry_point in sorted(_installed().items()):
        section = settings.get(name) if isinstance(settings, dict) else None
        if not (isinstance(section, dict) and section.get("enabled")):
            logger.info("channel %r is installed but off: set channels.%s.enabled in configuration.json", name, name)
            states[name] = {"state": "off"}
            continue
        host = ChannelHost(name, app["manager"], section)
        try:
            channel = entry_point.load()(host)
            await asyncio.wait_for(channel.start(), _START_TIMEOUT_S)
        except Exception as e:
            logger.exception("channel %r failed to start", name)
            host.close()
            states[name] = {"state": "failed", "error": f"{type(e).__name__}: {e}"}
            continue
        running[name] = _Running(host, channel)
        states[name] = {"state": "running"}
        logger.info("channel %r started", name)
    app["channels"] = running
    app["channel_states"] = states


async def stop_channels(app: web.Application) -> None:
    """aiohttp on_shutdown hook: stop the running channels."""
    for name, run in app.get("channels", {}).items():
        try:
            await asyncio.wait_for(run.channel.stop(), _START_TIMEOUT_S)
        except Exception:
            logger.exception("channel %r failed to stop cleanly", name)
        run.host.close()


async def handle_list_channels(request: web.Request) -> web.Response:
    """GET /api/channels -- installed channels and whether each is running, off, or failed."""
    from aiohttp import web

    states = request.app.get("channel_states", {})
    return web.json_response({"channels": [{"name": name, **state} for name, state in sorted(states.items())]})


def register(app: web.Application) -> None:
    app.on_startup.append(start_channels)
    # Before the sessions are stopped, so a channel can't resume one mid-shutdown.
    app.on_shutdown.insert(0, stop_channels)
    app.router.add_get("/api/channels", handle_list_channels)
