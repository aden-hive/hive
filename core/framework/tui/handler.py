"""
Logging Handler for TUI.
"""

import logging
from framework.tui.app import AdenTUI

class TUILogHandler(logging.Handler):
    """Redirects logging records to the TUI LogPane."""

    def __init__(self, app: AdenTUI):
        super().__init__()
        self.app = app

    def emit(self, record: logging.LogRecord) -> None:
        """Send log record to TUI."""
        log_entry = self.format(record)
        try:
            # We need to schedule the update on the main thread
            self.app.call_later(
                self.app.log_pane.write_log, log_entry
            )
        except Exception:
            # If app is closed or error, fallback
            pass
