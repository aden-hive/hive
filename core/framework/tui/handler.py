"""
Logging Handler for TUI.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from framework.tui.app import AdenTUI


class TUILogHandler(logging.Handler):
    """Redirects logging records to the TUI LogPane."""

    def __init__(self, app: "AdenTUI"):
        super().__init__()
        self.app = app

    def emit(self, record: logging.LogRecord) -> None:
        """Send log record to TUI."""
        # Avoid infinite recursion by ignoring textual logs
        if record.name.startswith("textual"):
            return

        try:
            if not hasattr(self.app, "is_ready") or not self.app.is_ready:
                return

            msg = self.format(record)
            # We need to schedule the update on the main thread
            self.app.call_later(self.app.log_pane.write_log, msg)
        except Exception:
            # If app is closed or error, fallback
            pass
