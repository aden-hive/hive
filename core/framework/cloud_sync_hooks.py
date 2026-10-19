"""Fire-and-forget cloud-sync push hooks for route handlers.

Route handlers call :func:`schedule_push` right after a successful local
write to propagate the change to the cloud immediately, rather than waiting
for the next ``cloud_sync`` reconcile tick.

Kept as a thin module separate from ``cloud_sync`` so route modules don't
import the heavy reconciler at import time, and so a hook can never fail or
block the request it was fired from.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


def schedule_push(kind: str, key: str) -> None:
    """Schedule a background push of one resource. Never raises.

    No-ops when cloud sync is disabled or there is no running event loop.
    """
    try:
        from framework.cloud_sync import _cloud_config

        if _cloud_config() is None:
            return
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Called outside an event loop — nothing to schedule onto.
        return
    except Exception:
        logger.debug("cloud_sync hook: schedule_push setup failed", exc_info=True)
        return
    loop.create_task(_safe_push(kind, key))


async def _safe_push(kind: str, key: str) -> None:
    try:
        from framework import cloud_sync

        await cloud_sync.push_resource(kind, key)
    except Exception:
        logger.debug("cloud_sync hook: push %s:%s failed", kind, key, exc_info=True)
