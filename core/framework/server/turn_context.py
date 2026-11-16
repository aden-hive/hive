"""Turn context: packages that put something in front of a queen before each of her turns.

A turn-context package names a factory in the ``hive.turn_context`` entry-point group::

    [project.entry-points."hive.turn_context"]
    mycontext = "mycontext:MyContext"

``hive serve`` calls the factory with a :class:`TurnContextHost` and starts what it returns when
the package's section of ``configuration.json`` enables it::

    {"turn_context": {"mycontext": {"enabled": true}}}

Before each turn that answers a user message, every started package gets the queen's id and the
message, and whatever text it returns reaches the queen as a ``<system-reminder>`` just ahead of
the message (it stays in the conversation like any reminder). Returning ``None`` adds nothing. A
package that is slower than :data:`CONTEXT_TIMEOUT_S` or raises is skipped for that turn; one that
fails to load or start is logged and left out. Neither ever holds a turn or takes the server down.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from aiohttp import web

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "hive.turn_context"
# start() should hand slow work (loading a model, building an index) to a background task.
_START_TIMEOUT_S = 30.0
# Context is fetched before the turn starts; past this the turn goes ahead without it.
CONTEXT_TIMEOUT_S = 5.0


@runtime_checkable
class TurnContext(Protocol):
    """What a turn-context factory returns."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def context(self, queen_id: str, message: str) -> str | None:
        """Text to put in front of ``queen_id`` before she answers ``message``, or ``None``.

        ``message`` is the user's message as the queen receives it, including any prefix a
        channel adds (sender, time, recent group chat).
        """
        ...


class TurnContextHost:
    """What Hive gives one turn-context package: its settings and a directory for its files."""

    def __init__(self, name: str, config: dict[str, Any]) -> None:
        self.name = name
        #: The package's section of ``configuration.json`` (``turn_context.<name>``).
        self.config = config

    @property
    def state_dir(self) -> Path:
        """``$HIVE_HOME/turn_context/<name>``: where the package keeps its own files."""
        from framework.config import HIVE_HOME

        path = HIVE_HOME / "turn_context" / self.name
        path.mkdir(parents=True, exist_ok=True)
        return path


# The started packages, by name. Module-level because every queen's loop reads it.
_running: dict[str, TurnContext] = {}


async def context_for(queen_id: str, message: str) -> str | None:
    """What the started packages want ``queen_id`` to see before she answers ``message``."""
    parts: list[str] = []
    for name, provider in list(_running.items()):
        try:
            text = await asyncio.wait_for(provider.context(queen_id, message), CONTEXT_TIMEOUT_S)
        except TimeoutError:
            logger.info("turn context %r took over %.0fs; this turn goes ahead without it", name, CONTEXT_TIMEOUT_S)
            continue
        except Exception:
            logger.warning("turn context %r failed for %s", name, queen_id, exc_info=True)
            continue
        if text and text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts) or None


def for_session(session: Any) -> Callable[[str], Awaitable[str | None]]:
    """The turn-context provider for a queen session's loop: asks for the session's queen.

    The queen is read on each call, since a new session picks its queen with the first message.
    """
    return lambda message: context_for(getattr(session, "queen_name", None) or "default", message)


def _installed() -> dict[str, Any]:
    from importlib.metadata import entry_points

    return {ep.name: ep for ep in entry_points(group=ENTRY_POINT_GROUP)}


async def start_turn_context(app: web.Application) -> None:
    """aiohttp on_startup hook: start each installed, enabled package."""
    from framework.config import get_hive_config

    settings = get_hive_config().get("turn_context") or {}
    for name, entry_point in sorted(_installed().items()):
        section = settings.get(name) if isinstance(settings, dict) else None
        if not (isinstance(section, dict) and section.get("enabled")):
            logger.info("turn context %r is installed but off: set turn_context.%s.enabled in configuration.json", name, name)
            continue
        try:
            provider = entry_point.load()(TurnContextHost(name, section))
            await asyncio.wait_for(provider.start(), _START_TIMEOUT_S)
        except Exception:
            logger.exception("turn context %r failed to start", name)
            continue
        _running[name] = provider
        logger.info("turn context %r started", name)


async def stop_turn_context(app: web.Application) -> None:
    """aiohttp on_shutdown hook: stop the started packages."""
    while _running:
        name, provider = _running.popitem()
        try:
            await asyncio.wait_for(provider.stop(), _START_TIMEOUT_S)
        except Exception:
            logger.exception("turn context %r failed to stop cleanly", name)


def register(app: web.Application) -> None:
    app.on_startup.append(start_turn_context)
    app.on_shutdown.append(stop_turn_context)
