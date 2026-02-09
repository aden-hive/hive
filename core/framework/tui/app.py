import logging
import platform
import subprocess
import time

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Footer, Input, Label

from framework.runtime.agent_runtime import AgentRuntime
from framework.runtime.event_bus import AgentEvent, EventType
from framework.tui.widgets.chat_repl import ChatRepl
from framework.tui.widgets.graph_view import GraphOverview
from framework.tui.widgets.log_pane import LogPane
from framework.tui.widgets.selectable_rich_log import SelectableRichLog


class StatusBar(Container):
    """Live status bar showing agent execution state."""

    DEFAULT_CSS = """
    StatusBar {
        dock: top;
        height: 1;
        background: $panel;
        color: $text;
        padding: 0 1;
    }
    StatusBar > Label {
        width: 100%;
    }
    """

    def __init__(self, graph_id: str = ""):
        super().__init__()
        self._graph_id = graph_id
        self._state = "idle"
        self._active_node: str | None = None
        self._node_detail: str = ""
        self._start_time: float | None = None
        self._final_elapsed: float | None = None

    def compose(self) -> ComposeResult:
        yield Label(id="status-content")

    def on_mount(self) -> None:
        self._refresh()
        self.set_interval(1.0, self._refresh)

    def _format_elapsed(self, seconds: float) -> str:
        total = int(seconds)
        hours, remainder = divmod(total, 3600)
        mins, secs = divmod(remainder, 60)
        if hours:
            return f"{hours}:{mins:02d}:{secs:02d}"
        return f"{mins}:{secs:02d}"

    def _refresh(self) -> None:
        parts: list[str] = []

        if self._graph_id:
            parts.append(f"[bold]{self._graph_id}[/bold]")

        if self._state == "idle":
            parts.append("[dim]○ idle[/dim]")
        elif self._state == "running":
            parts.append("[bold green]● running[/bold green]")
        elif self._state == "completed":
            parts.append("[green]✓ done[/green]")
        elif self._state == "failed":
            parts.append("[bold red]✗ failed[/bold red]")

        if self._active_node:
            node_str = f"[cyan]{self._active_node}[/cyan]"
            if self._node_detail:
                node_str += f" [dim]({self._node_detail})[/dim]"
            parts.append(node_str)

        if self._state == "running" and self._start_time:
            parts.append(f"[dim]{self._format_elapsed(time.time() - self._start_time)}[/dim]")
        elif self._final_elapsed is not None:
            parts.append(f"[dim]{self._format_elapsed(self._final_elapsed)}[/dim]")

        try:
            label = self.query_one("#status-content", Label)
            label.update(" │ ".join(parts))
        except Exception:
            pass

    def set_graph_id(self, graph_id: str) -> None:
        self._graph_id = graph_id
        self._refresh()

    def set_running(self, entry_node: str = "") -> None:
        self._state = "running"
        self._active_node = entry_node or None
        self._node_detail = ""
        self._start_time = time.time()
        self._final_elapsed = None
        self._refresh()

    def set_completed(self) -> None:
        self._state = "completed"
        if self._start_time:
            self._final_elapsed = time.time() - self._start_time
        self._active_node = None
        self._node_detail = ""
        self._start_time = None
        self._refresh()

    def set_failed(self, error: str = "") -> None:
        self._state = "failed"
        if self._start_time:
            self._final_elapsed = time.time() - self._start_time
        self._node_detail = error[:40] if error else ""
        self._start_time = None
        self._refresh()

    def set_active_node(self, node_id: str, detail: str = "") -> None:
        self._active_node = node_id
        self._node_detail = detail
        self._refresh()

    def set_node_detail(self, detail: str) -> None:
        self._node_detail = detail
        self._refresh()


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

    GraphOverview {
        height: 40%;
        background: $panel;
        padding: 0;
    }

    LogPane {
        height: 60%;
        background: $surface;
        padding: 0;
        margin-bottom: 1;
    }

    ChatRepl {
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

    RichLog {
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

    StatusBar {
        background: $panel;
        color: $text;
        height: 1;
        padding: 0 1;
    }

    Footer {
        background: $panel;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "ctrl_c", "Interrupt", show=False, priority=True),
        Binding("super+c", "ctrl_c", "Copy", show=False, priority=True),
        Binding("ctrl+s", "screenshot", "Screenshot (SVG)", show=True, priority=True),
        Binding("ctrl+z", "pause_execution", "Pause", show=True, priority=True),
        Binding("ctrl+r", "show_sessions", "Sessions", show=True, priority=True),
        Binding("tab", "focus_next", "Next Panel", show=True),
        Binding("shift+tab", "focus_previous", "Previous Panel", show=False),
    ]

    def __init__(
        self,
        runtime: AgentRuntime,
        resume_session: str | None = None,
        resume_checkpoint: str | None = None,
    ):
        super().__init__()

        self.runtime = runtime
        self.log_pane = LogPane()
        self.graph_view = GraphOverview(runtime)
        self.chat_repl = ChatRepl(runtime, resume_session, resume_checkpoint)
        self.status_bar = StatusBar(graph_id=runtime.graph.id)
        self.is_ready = False

    def open_url(self, url: str, *, new_tab: bool = True) -> None:
        """Override to use native `open` for file:// URLs on macOS."""
        if url.startswith("file://") and platform.system() == "Darwin":
            path = url.removeprefix("file://")
            subprocess.Popen(["open", path])
        else:
            super().open_url(url, new_tab=new_tab)

    def action_ctrl_c(self) -> None:
        # Check if any SelectableRichLog has an active selection to copy
        for widget in self.query(SelectableRichLog):
            if widget.selection is not None:
                text = widget.copy_selection()
                if text:
                    widget.clear_selection()
                    self.notify("Copied to clipboard", severity="information", timeout=2)
                    return

        self.notify("Press [b]q[/b] to quit", severity="warning", timeout=3)

    def compose(self) -> ComposeResult:
        yield self.status_bar

        yield Horizontal(
            Vertical(
                self.log_pane,
                self.graph_view,
                id="left-pane",
            ),
            self.chat_repl,
        )

        yield Footer()

    async def on_mount(self) -> None:
        """Called when app starts."""
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
        except Exception:
            pass

    def _poll_logs(self) -> None:
        """Poll the log queue and update UI."""
        if not self.is_ready:
            return

        try:
            while not self.log_queue.empty():
                record = self.log_queue.get_nowait()
                # Filter out framework/library logs
                if record.name.startswith(("textual", "LiteLLM", "litellm")):
                    continue

                self.log_pane.write_python_log(record)
        except Exception:
            pass

    _EVENT_TYPES = [
        EventType.LLM_TEXT_DELTA,
        EventType.CLIENT_OUTPUT_DELTA,
        EventType.TOOL_CALL_STARTED,
        EventType.TOOL_CALL_COMPLETED,
        EventType.EXECUTION_STARTED,
        EventType.EXECUTION_COMPLETED,
        EventType.EXECUTION_FAILED,
        EventType.NODE_LOOP_STARTED,
        EventType.NODE_LOOP_ITERATION,
        EventType.NODE_LOOP_COMPLETED,
        EventType.CLIENT_INPUT_REQUESTED,
        EventType.NODE_STALLED,
        EventType.GOAL_PROGRESS,
        EventType.GOAL_ACHIEVED,
        EventType.CONSTRAINT_VIOLATION,
        EventType.STATE_CHANGED,
        EventType.NODE_INPUT_BLOCKED,
    ]

    _LOG_PANE_EVENTS = frozenset(_EVENT_TYPES) - {
        EventType.LLM_TEXT_DELTA,
        EventType.CLIENT_OUTPUT_DELTA,
    }

    async def _init_runtime_connection(self) -> None:
        """Subscribe to runtime events with an async handler."""
        try:
            self._subscription_id = self.runtime.subscribe_to_events(
                event_types=self._EVENT_TYPES,
                handler=self._handle_event,
            )
        except Exception:
            pass

    async def _handle_event(self, event: AgentEvent) -> None:
        """Called from the agent thread — bridge to Textual's main thread."""
        try:
            self.call_from_thread(self._route_event, event)
        except Exception:
            pass

    def _route_event(self, event: AgentEvent) -> None:
        """Route incoming events to widgets. Runs on Textual's main thread."""
        if not self.is_ready:
            return

        try:
            et = event.type

            # --- Chat REPL events ---
            if et in (EventType.LLM_TEXT_DELTA, EventType.CLIENT_OUTPUT_DELTA):
                self.chat_repl.handle_text_delta(
                    event.data.get("content", ""),
                    event.data.get("snapshot", ""),
                )
            elif et == EventType.TOOL_CALL_STARTED:
                self.chat_repl.handle_tool_started(
                    event.data.get("tool_name", "unknown"),
                    event.data.get("tool_input", {}),
                )
            elif et == EventType.TOOL_CALL_COMPLETED:
                self.chat_repl.handle_tool_completed(
                    event.data.get("tool_name", "unknown"),
                    event.data.get("result", ""),
                    event.data.get("is_error", False),
                )
            elif et == EventType.EXECUTION_COMPLETED:
                self.chat_repl.handle_execution_completed(event.data.get("output", {}))
            elif et == EventType.EXECUTION_FAILED:
                self.chat_repl.handle_execution_failed(event.data.get("error", "Unknown error"))
            elif et == EventType.CLIENT_INPUT_REQUESTED:
                self.chat_repl.handle_input_requested(
                    event.node_id or event.data.get("node_id", ""),
                )

            # --- Graph view events ---
            if et in (
                EventType.EXECUTION_STARTED,
                EventType.EXECUTION_COMPLETED,
                EventType.EXECUTION_FAILED,
            ):
                self.graph_view.update_execution(event)

            if et == EventType.NODE_LOOP_STARTED:
                self.graph_view.handle_node_loop_started(event.node_id or "")
            elif et == EventType.NODE_LOOP_ITERATION:
                self.graph_view.handle_node_loop_iteration(
                    event.node_id or "",
                    event.data.get("iteration", 0),
                )
            elif et == EventType.NODE_LOOP_COMPLETED:
                self.graph_view.handle_node_loop_completed(event.node_id or "")
            elif et == EventType.NODE_STALLED:
                self.graph_view.handle_stalled(
                    event.node_id or "",
                    event.data.get("reason", ""),
                )

            if et == EventType.TOOL_CALL_STARTED:
                self.graph_view.handle_tool_call(
                    event.node_id or "",
                    event.data.get("tool_name", "unknown"),
                    started=True,
                )
            elif et == EventType.TOOL_CALL_COMPLETED:
                self.graph_view.handle_tool_call(
                    event.node_id or "",
                    event.data.get("tool_name", "unknown"),
                    started=False,
                )

            # --- Status bar events ---
            if et == EventType.EXECUTION_STARTED:
                entry_node = event.data.get("entry_node") or (
                    self.runtime.graph.entry_node if self.runtime else ""
                )
                self.status_bar.set_running(entry_node)
            elif et == EventType.EXECUTION_COMPLETED:
                self.status_bar.set_completed()
            elif et == EventType.EXECUTION_FAILED:
                self.status_bar.set_failed(event.data.get("error", ""))
            elif et == EventType.NODE_LOOP_STARTED:
                self.status_bar.set_active_node(event.node_id or "", "thinking...")
            elif et == EventType.NODE_LOOP_ITERATION:
                self.status_bar.set_node_detail(f"step {event.data.get('iteration', '?')}")
            elif et == EventType.TOOL_CALL_STARTED:
                self.status_bar.set_node_detail(f"{event.data.get('tool_name', '')}...")
            elif et == EventType.TOOL_CALL_COMPLETED:
                self.status_bar.set_node_detail("thinking...")
            elif et == EventType.NODE_STALLED:
                self.status_bar.set_node_detail(f"stalled: {event.data.get('reason', '')}")

            # --- Log pane events ---
            if et in self._LOG_PANE_EVENTS:
                self.log_pane.write_event(event)
        except Exception:
            pass

    def save_screenshot(self, filename: str | None = None) -> str:
        """Save a screenshot of the current screen as SVG (viewable in browsers).

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
        chat_widget = self.query_one(ChatRepl)
        original_chat_border = chat_widget.styles.border_left
        chat_widget.styles.border_left = ("none", "transparent")

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
            chat_widget.styles.border_left = original_chat_border
            for i, input_widget in enumerate(input_widgets):
                input_widget.styles.border = original_input_borders[i]

        return str(filepath)

    def action_screenshot(self) -> None:
        """Take a screenshot (bound to Ctrl+S)."""
        try:
            filepath = self.save_screenshot()
            self.notify(
                f"Screenshot saved: {filepath} (SVG - open in browser)",
                severity="information",
                timeout=5,
            )
        except Exception as e:
            self.notify(f"Screenshot failed: {e}", severity="error", timeout=5)

    def action_pause_execution(self) -> None:
        """Immediately pause execution by cancelling task (bound to Ctrl+Z)."""
        try:
            chat_repl = self.query_one(ChatRepl)
            if not chat_repl._current_exec_id:
                self.notify(
                    "No active execution to pause",
                    severity="information",
                    timeout=3,
                )
                return

            # Find and cancel the execution task - executor will catch and save state
            task_cancelled = False
            for stream in self.runtime._streams.values():
                exec_id = chat_repl._current_exec_id
                task = stream._execution_tasks.get(exec_id)
                if task and not task.done():
                    task.cancel()
                    task_cancelled = True
                    self.notify(
                        "⏸ Execution paused - state saved",
                        severity="information",
                        timeout=3,
                    )
                    break

            if not task_cancelled:
                self.notify(
                    "Execution already completed",
                    severity="information",
                    timeout=2,
                )
        except Exception as e:
            self.notify(
                f"Error pausing execution: {e}",
                severity="error",
                timeout=5,
            )

    def action_show_sessions(self) -> None:
        """Show sessions list (bound to Ctrl+R)."""
        # Send /sessions command to chat input
        try:
            chat_repl = self.query_one(ChatRepl)
            chat_input = chat_repl.query_one("#chat-input", Input)
            chat_input.value = "/sessions"
            # Trigger submission
            self.notify(
                "💡 Type /sessions in the chat to see all sessions",
                severity="information",
                timeout=3,
            )
        except Exception:
            self.notify(
                "Use /sessions command to see all sessions",
                severity="information",
                timeout=3,
            )

    async def on_unmount(self) -> None:
        """Cleanup on app shutdown - cancel execution which will save state."""
        self.is_ready = False

        # Cancel any active execution - the executor will catch CancelledError
        # and save current state as paused (no waiting needed!)
        try:
            import asyncio

            chat_repl = self.query_one(ChatRepl)
            if chat_repl._current_exec_id:
                # Find the stream with this execution
                for stream in self.runtime._streams.values():
                    exec_id = chat_repl._current_exec_id
                    task = stream._execution_tasks.get(exec_id)
                    if task and not task.done():
                        # Cancel the task - executor will catch and save state
                        task.cancel()
                        try:
                            # Wait for executor to save state (may take a few seconds)
                            # Longer timeout for quit to ensure state is properly saved
                            await asyncio.wait_for(task, timeout=5.0)
                        except (TimeoutError, asyncio.CancelledError):
                            # Expected - task was cancelled
                            # If timeout, state may not be fully saved
                            pass
                        except Exception:
                            # Ignore other exceptions during cleanup
                            pass
                        break
        except Exception:
            pass

        try:
            if hasattr(self, "_subscription_id"):
                self.runtime.unsubscribe_from_events(self._subscription_id)
        except Exception:
            pass
        try:
            if hasattr(self, "queue_handler"):
                logging.getLogger().removeHandler(self.queue_handler)
        except Exception:
            pass
