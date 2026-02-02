"""
Log Pane Widget - Uses RichLog for reliable rendering.
"""

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import RichLog


class LogPane(Container):
    """Widget to display logs with reliable rendering."""

    DEFAULT_CSS = """
    LogPane {
        width: 100%;
        height: 100%;
    }

    LogPane > RichLog {
        width: 100%;
        height: 100%;
        background: $surface;
        border: none;
        scrollbar-background: $panel;
        scrollbar-color: $primary;
    }
    """

    def compose(self) -> ComposeResult:
        # RichLog is designed for log display and doesn't have TextArea's rendering issues
        yield RichLog(id="main-log", highlight=True, markup=True, auto_scroll=True)

    def write_log(self, message: str) -> None:
        """Write a log message to the log pane."""
        try:
            # Check if widget is mounted
            if not self.is_mounted:
                return

            log = self.query_one("#main-log", RichLog)

            # Check if log is mounted
            if not log.is_mounted:
                return

            # Write message - RichLog handles rendering correctly
            log.write(message)

        except Exception as e:
            # Widget might not be ready
            with open("tui_debug.log", "a") as f:
                f.write(f"ERROR in write_log: {e}\n")
