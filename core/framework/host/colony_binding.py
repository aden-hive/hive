"""Single source of truth for "which colony does this code belong to".

Before this module existed, three loose fields (``colony_id``,
``colony_id``, ``tracker_db_path``) were threaded around the codebase
to identify a colony. The fields disagreed about meaning depending on
who set them:

- ``colony_id`` was sometimes a session UUID (event-bus scope), sometimes
  an on-disk colony name. Tools that synthesized filesystem paths from
  it silently created shadow ``colonies/<session_id>/`` directories.
- ``colony_id`` was the on-disk identity but could be ``None``.
- ``tracker_db_path`` was an absolute path baked in at fork time, but
  callers that forgot to inject it triggered the dual-meaning fallback.

A ``ColonyBinding`` collapses those three into one immutable value: if
you have a binding, you know the colony name, its on-disk directory,
and its ``tracker.db`` path; if you don't, you are not in a colony and
colony tools should refuse rather than guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ColonyBinding:
    """Immutable identity of a single on-disk colony.

    The binding is constructed once per fork and threaded — via
    ``input_data`` for workers and via the ``ToolRegistry`` execution
    context for the queen — into every tool that needs to know which
    colony owns the call. Tools that don't have a binding refuse the
    call; they never invent a path.
    """

    name: str
    dir: Path
    tracker_db: Path

    @classmethod
    def for_name(cls, name: str) -> ColonyBinding:
        """Resolve standard on-disk paths for ``name``.

        Does NOT create the directory or the tracker DB — that's
        ``ensure_tracker_db``'s job, called by the fork flow. Use this
        when you already know the colony exists (the dir was created by
        ``fork_session_into_colony``) and just need a binding object.
        """
        from framework.config import colony_dir, colony_tracker_db_path

        return cls(
            name=name,
            dir=colony_dir(name),
            tracker_db=colony_tracker_db_path(name),
        )

    def to_dict(self) -> dict[str, str]:
        """Serialize for ``input_data`` JSON. Paths become absolute strings."""
        return {
            "name": self.name,
            "dir": str(self.dir),
            "tracker_db": str(self.tracker_db),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ColonyBinding | None:
        """Reverse of :meth:`to_dict`. Returns None on malformed input."""
        if not isinstance(data, dict):
            return None
        name = data.get("name")
        dir_ = data.get("dir")
        tracker = data.get("tracker_db")
        if not (isinstance(name, str) and name and isinstance(dir_, str) and isinstance(tracker, str)):
            return None
        return cls(name=name, dir=Path(dir_), tracker_db=Path(tracker))


def current_binding() -> ColonyBinding | None:
    """Return the binding for the current tool execution, or None.

    Reads from the ``ToolRegistry`` execution context. Tools that depend
    on a colony binding (tracker_*, anything that writes under the colony
    dir) should call this and return a clear "no colony" error when it
    returns ``None``, rather than synthesizing paths from session UUIDs.
    """
    from framework.tasks.tools._context import current_context

    ctx = current_context()
    raw = ctx.get("binding")
    if isinstance(raw, ColonyBinding):
        return raw
    if isinstance(raw, dict):
        return ColonyBinding.from_dict(raw)
    return None


__all__ = ["ColonyBinding", "current_binding"]
