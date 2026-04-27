"""Task list id resolution.

Under the corrected model (see plan §5):

  - Every agent session owns one task list:  ``session:{agent_id}:{session_id}``
  - The colony has a separate template list:  ``colony:{colony_id}``

``resolve_task_list_id(ctx)`` returns the agent's OWN session list id —
what the four task tools write to. The colony template is addressed via
the dedicated ``colony_template_*`` tools and the UI; never via the four
session tools.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def session_task_list_id(agent_id: str, session_id: str) -> str:
    return f"session:{agent_id}:{session_id}"


def colony_task_list_id(colony_id: str) -> str:
    return f"colony:{colony_id}"


def parse_task_list_id(task_list_id: str) -> dict[str, str]:
    """Decode a task_list_id into its component parts.

    Returns a dict with at least ``kind`` ("session" / "colony" / "unscoped"
    / "raw"), and the relevant ids when applicable.
    """
    if task_list_id.startswith("session:"):
        rest = task_list_id[len("session:") :]
        agent_id, _, session_id = rest.partition(":")
        return {"kind": "session", "agent_id": agent_id, "session_id": session_id}
    if task_list_id.startswith("colony:"):
        return {"kind": "colony", "colony_id": task_list_id[len("colony:") :]}
    if task_list_id.startswith("unscoped:"):
        return {"kind": "unscoped", "agent_id": task_list_id[len("unscoped:") :]}
    return {"kind": "raw", "value": task_list_id}


def resolve_task_list_id(ctx: Any) -> str:
    """Return the agent's own session-scoped task list id.

    Resolution priority:

      1. ``HIVE_TASK_LIST_ID`` env var (test/CLI override)
      2. ``ctx.task_list_id`` if already populated by the runner
      3. ``session:{ctx.agent_id}:{ctx.run_id or ctx.execution_id}``
      4. ``unscoped:{ctx.agent_id}`` sentinel (should not happen in prod)
    """
    override = os.environ.get("HIVE_TASK_LIST_ID")
    if override:
        return override

    existing = getattr(ctx, "task_list_id", None)
    if existing:
        return existing

    agent_id = getattr(ctx, "agent_id", None) or ""
    session_id = (
        getattr(ctx, "run_id", None) or getattr(ctx, "execution_id", None) or getattr(ctx, "stream_id", None) or ""
    )
    if agent_id and session_id:
        return session_task_list_id(agent_id, session_id)

    fallback = f"unscoped:{agent_id or 'unknown'}"
    logger.warning(
        "resolve_task_list_id falling back to %s — agent_id=%r session_id=%r",
        fallback,
        agent_id,
        session_id,
    )
    return fallback
