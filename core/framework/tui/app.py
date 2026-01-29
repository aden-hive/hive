
"""
TUI Application for Aden Hive.
"""

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Label
from textual.containers import Container, Horizontal, Vertical
from textual.binding import Binding

from framework.runtime.agent_runtime import AgentRuntime
from framework.tui.widgets.log_pane import LogPane
from framework.tui.widgets.graph_view import GraphOverview
from framework.tui.widgets.chat_repl import ChatRepl

class AdenTUI(App):
    """Aden Interactive Terminal Dashboard."""

    CSS = """
    Screen {
        layout: vertical;
    }

    #left-pane {
        width: 1fr;
        height: 100%;
        border: solid green;
    }

    #right-pane {
        width: 2fr;
        height: 100%;
        layout: vertical;
    }
    
    #log-pane-container {
        height: 70%;
        border: solid blue;
    }

    #chat-repl-container {
        height: 30%;
        border: solid yellow;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("p", "toggle_pause", "Pause/Resume"),
        Binding("s", "step", "Step"),
    ]

    def __init__(self, runtime: AgentRuntime):
        super().__init__()
        self.runtime = runtime
        self.log_pane = LogPane()
        self.graph_view = GraphOverview()
        self.chat_repl = ChatRepl(runtime)

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield self.log_pane
        yield self.graph_view
        yield self.chat_repl
        yield Footer()

    async def on_mount(self) -> None:
        """Called when app starts."""
        self.title = "Aden TUI Dashboard"
        
        # Subscribe to all events
        self.runtime.subscribe_to_events(
            event_types=[], # Empty list usually means all, or we need to specify
            handler=self.on_event
        )
        
        # Setup logging redirection
        import logging
        from framework.tui.handler import TUILogHandler
        
        self.log_handler = TUILogHandler(self)
        self.log_handler.setLevel(logging.INFO)
        
        # Add to root logger
        # logging.getLogger().addHandler(self.log_handler)
        
        
        self.is_ready = True
            
    def on_unmount(self) -> None:
        self.is_ready = False
        import logging
        if hasattr(self, "log_handler"):
            logging.getLogger().removeHandler(self.log_handler)

    async def on_event(self, event) -> None:
        pass
