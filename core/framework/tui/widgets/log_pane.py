"""
Log Pane Widget.
"""

from textual.widgets import RichLog
from textual.app import ComposeResult
from textual.containers import Container

class LogPane(Container):
    """Widget to display logs."""

    def compose(self) -> ComposeResult:
        yield RichLog(highlight=True, markup=True, id="main-log")

    def write_log(self, message: str) -> None:
        """Write a log message to the log pane."""
        try:
            text_log = self.query_one("#main-log", RichLog)
            text_log.write(message)
        except Exception:
            # Widget might not be ready
            pass
