"""Shared context for queen lifecycle tools.

All queen tools receive this context instead of closing over
individual variables from the registration function.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class QueenToolContext:
    """Shared state passed to all queen lifecycle tool implementations."""

    session: Any  # Session or WorkerSessionAdapter
    session_manager: Any | None = None
    manager_session_id: str | None = None
    phase_state: Any | None = None  # QueenPhaseState
    registry: Any = None  # ToolRegistry

    def get_runtime(self):
        """Get current graph runtime from session (late-binding)."""
        return getattr(self.session, "graph_runtime", None)

    def update_meta(self, updates: dict) -> None:
        """Update session metadata JSON."""
        if self.session_manager is None or self.manager_session_id is None:
            return
        try:
            srv_session = self.session_manager.get_session(self.manager_session_id)
            if srv_session is None:
                return
            meta_path = getattr(srv_session, "meta_path", None)
            if meta_path is None:
                return
            import pathlib

            meta_file = pathlib.Path(meta_path)
            if meta_file.exists():
                data = json.loads(meta_file.read_text(encoding="utf-8"))
            else:
                data = {}
            data.update(updates)
            meta_file.write_text(json.dumps(data, indent=2) + "\n")
        except Exception:
            logger.debug("Failed to update session meta", exc_info=True)
