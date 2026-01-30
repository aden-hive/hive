from textual.app import App, ComposeResult
from textual.widgets import Label, Header, Footer
from textual.containers import Container, Horizontal, Vertical
from textual.binding import Binding
from framework.runtime.agent_runtime import AgentRuntime
from framework.tui.widgets.log_pane import LogPane
from framework.tui.widgets.graph_view import GraphOverview
from framework.tui.widgets.chat_repl import ChatRepl
import logging

class AdenTUI(App):
    CSS = """
    Screen {
        layout: vertical;
    }

    #left-pane {
        width: 60%;
        height: 100%;
        layout: vertical;
    }
    
    #graph-overview-container {
        height: 40%;
        border: solid green;
    }

    #log-pane-container {
        height: 60%;
        border: solid blue;
    }

    #chat-repl-container {
        width: 40%;
        height: 100%;
        border: solid yellow;
    }
    
    #chat-history {
        height: 1fr;
        width: 100%;
    }
    """
    
    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("tab", "focus_next", "Next Panel", show=True),
        Binding("shift+tab", "focus_previous", "Previous Panel", show=False),
    ]

    def __init__(self, runtime: AgentRuntime):
        with open("tui_debug.log", "a") as f:
            f.write("DEBUG: AdenTUI.__init__ started\n")
        
        print("DEBUG: AdenTUI.__init__ called")
        super().__init__()
        
        self.runtime = runtime
        self.log_pane = LogPane()
        self.graph_view = GraphOverview()
        self.chat_repl = ChatRepl(runtime)
        self.is_ready = False
        
        with open("tui_debug.log", "a") as f:
            f.write("DEBUG: Widgets initialized\n")

    def compose(self) -> ComposeResult:
        with open("tui_debug.log", "a") as f:
            f.write("DEBUG: compose() called\n")
        
        yield Header()
        
        yield Horizontal(
            Vertical(
                Container(self.log_pane, id="log-pane-container"),
                Container(self.graph_view, id="graph-overview-container"),
                id="left-pane",
            ),
            Container(self.chat_repl, id="chat-repl-container"),
        )
        
        yield Footer()
        
        with open("tui_debug.log", "a") as f:
            f.write("DEBUG: compose() complete\n")

    async def on_mount(self) -> None:
        """Called when app starts."""
        with open("tui_debug.log", "a") as f:
            f.write("DEBUG: on_mount() called\n")
        
        self.title = "Aden TUI Dashboard"
        self.is_ready = True
        
        # Add logging setup
        self._setup_logging_queue()
        
        # Add event subscription with delay to ensure TUI is fully initialized
        self.call_later(self._init_runtime_connection)
        
        # Add a test log message
        logging.info("TUI Dashboard initialized successfully")
        logging.info("Waiting for agent execution to start...")
        
        with open("tui_debug.log", "a") as f:
            f.write("DEBUG: on_mount() complete\n")

    def _setup_logging_queue(self) -> None:
        """Setup a thread-safe queue for logs."""
        try:
            import queue
            from logging.handlers import QueueHandler
            
            self.log_queue = queue.Queue()
            self.queue_handler = QueueHandler(self.log_queue)
            self.queue_handler.setLevel(logging.INFO)
            
            # Add to root logger
            root_logger = logging.getLogger()
            if self.queue_handler not in root_logger.handlers:
                root_logger.addHandler(self.queue_handler)
                
            # Start polling
            self.set_interval(0.1, self._poll_logs)
            
            with open("tui_debug.log", "a") as f:
                f.write("DEBUG: Logging setup complete\n")
        except Exception as e:
            with open("tui_debug.log", "a") as f:
                f.write(f"ERROR in _setup_logging_queue: {e}\n")

    def _poll_logs(self) -> None:
        """Poll the log queue and update UI."""
        if not self.is_ready:
            return
        
        try:
            count = 0
            while not self.log_queue.empty():
                record = self.log_queue.get_nowait()
                if record.name.startswith("textual"):
                    continue
                
                msg = logging.Formatter().format(record)
                self.log_pane.write_log(msg)
                count += 1
                
            if count > 0:
                with open("tui_debug.log", "a") as f:
                    f.write(f"DEBUG: _poll_logs processed {count} messages\n")
        except Exception as e:
            with open("tui_debug.log", "a") as f:
                f.write(f"ERROR in _poll_logs: {e}\n")

    async def _init_runtime_connection(self) -> None:
        """Subscribe to runtime events with defensive error handling."""
        try:
            with open("tui_debug.log", "a") as f:
                f.write("DEBUG: _init_runtime_connection called\n")
            
            # Use call_soon_threadsafe wrapper for the handler
            def safe_event_handler(event):
                """Thread-safe event handler wrapper."""
                try:
                    # Schedule on the main loop
                    self.call_from_thread(self._handle_event_sync, event)
                except Exception as e:
                    with open("tui_debug.log", "a") as f:
                        f.write(f"ERROR in safe_event_handler: {e}\n")
            
            self.runtime.subscribe_to_events(
                event_types=[],
                handler=safe_event_handler
            )
            
            with open("tui_debug.log", "a") as f:
                f.write("DEBUG: Event subscription complete\n")
        except Exception as e:
            with open("tui_debug.log", "a") as f:
                f.write(f"ERROR in _init_runtime_connection: {e}\n")
            import traceback
            traceback.print_exc()

    def _handle_event_sync(self, event) -> None:
        """Handle events on the main thread (called via call_from_thread)."""
        try:
            with open("tui_debug.log", "a") as f:
                f.write(f"DEBUG: _handle_event_sync called with event: {event}\n")
            
            if not self.is_ready:
                with open("tui_debug.log", "a") as f:
                    f.write("DEBUG: App not ready, skipping event\n")
                return
            
            # Update graph view
            if hasattr(event, "type"):
                with open("tui_debug.log", "a") as f:
                    f.write(f"DEBUG: Event has type: {event.type}\n")
                    
                if hasattr(event.type, "value"):
                    event_type = event.type.value
                    with open("tui_debug.log", "a") as f:
                        f.write(f"DEBUG: Event type value: {event_type}\n")
                        
                    if event_type.startswith("execution_"):
                        self.graph_view.update_execution(event)
                        
                        with open("tui_debug.log", "a") as f:
                            f.write(f"DEBUG: Handled event {event_type}\n")
        except Exception as e:
            with open("tui_debug.log", "a") as f:
                f.write(f"ERROR in _handle_event_sync: {e}\n")
            import traceback
            with open("tui_debug.log", "a") as f:
                f.write(f"{traceback.format_exc()}\n")

    async def on_unmount(self) -> None:
        """Cleanup on app shutdown."""
        self.is_ready = False
        try:
            if hasattr(self, "queue_handler"):
                logging.getLogger().removeHandler(self.queue_handler)
        except Exception:
            pass
