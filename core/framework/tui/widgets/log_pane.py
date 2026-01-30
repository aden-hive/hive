"""
Log Pane Widget.
"""

from textual.widgets import TextArea
from textual.app import ComposeResult
from textual.containers import Container

class LogPane(Container):
    """Widget to display logs with text selection support."""
    
    DEFAULT_CSS = """
    LogPane {
        width: 100%;
        height: 100%;
    }
    
    LogPane > TextArea {
        width: 100%;
        height: 100%;
        border: solid $accent;
    }
    
    LogPane > TextArea:focus {
        border: solid $accent-lighten-2;
    }
    """

    def compose(self) -> ComposeResult:
        # TextArea supports text selection and copying
        text_area = TextArea(
            id="main-log",
            read_only=True,
            show_line_numbers=False,
            language="text"
        )
        text_area.cursor_blink = False  # Disable cursor blinking for read-only
        yield text_area

    def write_log(self, message: str) -> None:
        """Write a log message to the log pane."""
        try:
            text_area = self.query_one("#main-log", TextArea)
            # Append message with newline
            current_text = text_area.text
            if current_text:
                text_area.text = current_text + "\n" + message
            else:
                text_area.text = message
            
            # Auto-scroll to bottom
            text_area.scroll_end(animate=False)
        except Exception as e:
            # Widget might not be ready
            with open("tui_debug.log", "a") as f:
                f.write(f"ERROR in write_log: {e}\n")

