import logging

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Footer, Label

from framework.runtime.agent_runtime import AgentRuntime
from framework.tui.widgets.chat_repl import ChatRepl
from framework.tui.widgets.graph_view import GraphOverview
from framework.tui.widgets.log_pane import LogPane


class StaticHeader(Container):
    """Custom static header that replaces standard Header widget."""

    DEFAULT_CSS = """
    StaticHeader {
        dock: top;
        height: 1;
        background: $primary;
        color: $text;
        text-style: bold;
        align: center middle;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label(self.app.title)


class AdenTUI(App):
    TITLE = "Aden TUI Dashboard"
    COMMAND_PALETTE_BINDING = "ctrl+o"
    CSS = """
    Screen {
        layout: vertical;
        background: $surface;
    }

    #left-pane {
        width: 60%;
        height: 100%;
        layout: vertical;
        background: $surface;
    }

    #graph-overview-container {
        height: 40%;
        background: $panel;
        padding: 0;
    }

    #log-pane-container {
        height: 60%;
        background: $surface;
        padding: 0;
        margin-bottom: 1;
    }

    #chat-repl-container {
        width: 40%;
        height: 100%;
        background: $panel;
        border-left: tall $primary;
        padding: 0;
    }

    #chat-history {
        height: 1fr;
        width: 100%;
        background: $surface;
        border: none;
        scrollbar-background: $panel;
        scrollbar-color: $primary;
    }

    TextArea {
        background: $surface;
        border: none;
        scrollbar-background: $panel;
        scrollbar-color: $primary;
    }

    Input {
        background: $surface;
        border: tall $primary;
        margin-top: 1;
    }

    Input:focus {
        border: tall $accent;
    }

    StaticHeader {
        background: $primary;
        color: $text;
        text-style: bold;
        height: 1;
    }

    /* Force height 1 even if tall class is added (prevents expansion) */
    StaticHeader.-tall {
        height: 1;
    }

    StaticHeader > .header--title {
        text-style: bold;
    }

    /* Hide the clock icon and top-left icon/button */
    Header .header--clock, StaticHeader .header--clock,
    Header .header--icon, StaticHeader .header--icon {
        display: none !important;
    }

    Footer {
        background: $panel;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+s", "screenshot", "Screenshot (SVG)", show=True, priority=True),
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
        self.graph_view = GraphOverview(runtime)
        self.chat_repl = ChatRepl(runtime)
        self.is_ready = False

        with open("tui_debug.log", "a") as f:
            f.write("DEBUG: Widgets initialized\n")

    def compose(self) -> ComposeResult:
        with open("tui_debug.log", "a") as f:
            f.write("DEBUG: compose() called\n")

        yield StaticHeader()

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

        # Add logging setup
        self._setup_logging_queue()

        # Set ready immediately so _poll_logs can process messages
        self.is_ready = True

        # Add event subscription with delay to ensure TUI is fully initialized
        self.call_later(self._init_runtime_connection)

        # Delay initial log messages until layout is fully rendered
        def write_initial_logs():
            logging.info("TUI Dashboard initialized successfully")
            logging.info("Waiting for agent execution to start...")

        # Wait for layout to be fully rendered before writing logs
        self.set_timer(0.2, write_initial_logs)

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

            # Get root logger
            root_logger = logging.getLogger()

            # Remove ALL existing handlers to prevent stdout output
            # This is critical - StreamHandlers cause text to appear in header
            for handler in root_logger.handlers[:]:
                root_logger.removeHandler(handler)

            # Add ONLY our queue handler
            root_logger.addHandler(self.queue_handler)
            root_logger.setLevel(logging.INFO)

            # Suppress LiteLLM logging completely
            litellm_logger = logging.getLogger("LiteLLM")
            litellm_logger.setLevel(logging.CRITICAL)  # Only show critical errors
            litellm_logger.propagate = False  # Don't propagate to root logger

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
                # Filter out framework/library logs
                if record.name.startswith(("textual", "LiteLLM", "litellm")):
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

            self.runtime.subscribe_to_events(event_types=[], handler=safe_event_handler)

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

                    if event_type.startswith(("execution_", "node_")):
                        self.graph_view.update_execution(event)

                        with open("tui_debug.log", "a") as f:
                            f.write(f"DEBUG: Handled event {event_type}\n")
        except Exception as e:
            with open("tui_debug.log", "a") as f:
                f.write(f"ERROR in _handle_event_sync: {e}\n")
            import traceback

            with open("tui_debug.log", "a") as f:
                f.write(f"{traceback.format_exc()}\n")

    def save_png_screenshot(self, filename: str | None = None) -> str:
        """Save a screenshot of the current screen as SVG (viewable in browsers).

        Note: Saves as SVG format since PNG conversion requires system libraries.
        SVG files can be opened in any web browser or converted to PNG using online tools.

        Args:
            filename: Optional filename for the screenshot. If None, generates timestamp-based name.

        Returns:
            Path to the saved SVG file.
        """
        from datetime import datetime
        from pathlib import Path

        # Create screenshots directory
        screenshots_dir = Path("screenshots")
        screenshots_dir.mkdir(exist_ok=True)

        # Generate filename if not provided
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"tui_screenshot_{timestamp}.svg"

        # Ensure .svg extension
        if not filename.endswith(".svg"):
            filename += ".svg"

        # Full path
        filepath = screenshots_dir / filename

        # Temporarily hide borders for cleaner screenshot
        chat_container = self.query_one("#chat-repl-container")
        original_chat_border = chat_container.styles.border_left
        chat_container.styles.border_left = ("none", "transparent")

        # Hide all Input widget borders
        input_widgets = self.query("Input")
        original_input_borders = []
        for input_widget in input_widgets:
            original_input_borders.append(input_widget.styles.border)
            input_widget.styles.border = ("none", "transparent")

        try:
            # Get SVG data from Textual and save it
            svg_data = self.export_screenshot()
            filepath.write_text(svg_data, encoding="utf-8")
        finally:
            # Restore the original borders
            chat_container.styles.border_left = original_chat_border
            for i, input_widget in enumerate(input_widgets):
                input_widget.styles.border = original_input_borders[i]

        return str(filepath)

    def action_screenshot(self) -> None:
        """Take a screenshot (bound to Ctrl+S)."""
        try:
            filepath = self.save_png_screenshot()
            self.notify(
                f"Screenshot saved: {filepath} (SVG - open in browser)",
                severity="information",
                timeout=5,
            )
        except Exception as e:
            self.notify(f"Screenshot failed: {e}", severity="error", timeout=5)

    async def on_unmount(self) -> None:
        """Cleanup on app shutdown."""
        self.is_ready = False
        try:
            if hasattr(self, "queue_handler"):
                logging.getLogger().removeHandler(self.queue_handler)
        except Exception:
            pass
