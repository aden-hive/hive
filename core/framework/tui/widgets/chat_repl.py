"""
Chat / REPL Widget - Uses RichLog for append-only, selection-safe display.

Streaming display approach:
- The #streaming-output RichLog shows live LLM output as it streams in.
  Each text delta appends new tokens so the user sees the full response forming.
- On flush (tool call, node switch, execution complete, input requested) the
  accumulated text is written to #chat-history as permanent history and the
  streaming area is cleared.
- The #processing-indicator Label shows brief status messages (tool names, etc.).
- Tool events are written directly to RichLog as discrete status lines.

Client-facing input:
- When a client_facing=True EventLoopNode emits CLIENT_INPUT_REQUESTED, the
  ChatRepl transitions to "waiting for input" state: input is re-enabled and
  subsequent submissions are routed to runtime.inject_input() instead of
  starting a new execution.
"""

import asyncio
import logging
import re
import shutil
import threading
from pathlib import Path
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Label, TextArea

from framework.runtime.agent_runtime import AgentRuntime
from framework.runtime.event_bus import AgentEvent
from framework.tui.widgets.log_pane import format_event, format_python_log
from framework.tui.widgets.selectable_rich_log import SelectableRichLog as RichLog


class ChatTextArea(TextArea):
    """TextArea that submits on Enter and inserts newlines on Shift+Enter (or Ctrl+J)."""

    class Submitted(Message):
        """Posted when the user presses Enter."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    async def _on_key(self, event) -> None:
        if event.key == "enter":
            text = self.text.strip()
            self.clear()
            if text:
                self.post_message(self.Submitted(text))
            event.stop()
            event.prevent_default()
        elif event.key in ("shift+enter", "ctrl+j"):
            event.key = "enter"
            await super()._on_key(event)
        else:
            await super()._on_key(event)


class ChatRepl(Vertical):
    """Widget for interactive chat/REPL."""

    DEFAULT_CSS = """
    ChatRepl {
        width: 100%;
        height: 100%;
        layout: vertical;
    }

    ChatRepl > #input-row {
        width: 100%;
        height: auto;
        dock: bottom;
    }

    ChatRepl > #input-row > ChatTextArea {
        width: 1fr;
        height: auto;
        max-height: 7;
        dock: none;
        margin-top: 1;
    }

    ChatRepl > #input-row > #action-button {
        width: auto;
        height: auto;
        min-width: 10;
        margin-top: 1;
        margin-left: 1;
        border: none;
        dock: none;
    }

    ChatRepl > #input-row > #action-button.send-mode {
        background: $success;
        color: $text;
    }

    ChatRepl > #input-row > #action-button.send-mode:hover {
        background: $success-darken-1;
    }

    ChatRepl > #input-row > #action-button.pause-mode {
        background: red;
        color: white;
    }

    ChatRepl > #input-row > #action-button.pause-mode:hover {
        background: darkred;
    }

    ChatRepl > #input-row > #action-button:disabled {
        background: $panel;
        color: $text-muted;
        opacity: 0.4;
    }

    ChatRepl > RichLog {
        width: 100%;
        height: 1fr;
        background: $surface;
        border: none;
        scrollbar-background: $panel;
        scrollbar-color: $primary;
    }

    ChatRepl > #streaming-output {
        width: 100%;
        height: auto;
        min-height: 0;
        max-height: 20%;
        background: $panel;
        border-top: solid $primary 40%;
        display: none;
        scrollbar-background: $panel;
        scrollbar-color: $primary;
        padding: 0 1;
    }

    ChatRepl > #processing-indicator {
        width: 100%;
        height: auto;
        max-height: 4;
        background: $primary 20%;
        color: $text;
        text-style: bold;
        display: none;
    }

    ChatRepl > #input-row > ChatTextArea {
        background: $surface;
        border: tall $primary;
    }

    ChatRepl > #input-row > ChatTextArea:focus {
        border: tall $accent;
    }
    """

    def __init__(
        self,
        runtime: AgentRuntime,
        resume_session: str | None = None,
        resume_checkpoint: str | None = None,
    ):
        super().__init__()
        self.runtime = runtime
        self._current_exec_id: str | None = None
        self._streaming_snapshot: str = ""
        self._streaming_written: int = 0  # chars already written to streaming-output
        self._waiting_for_input: bool = False
        self._input_node_id: str | None = None
        self._input_graph_id: str | None = None
        self._pending_ask_question: str = ""
        self._active_node_id: str | None = None  # Currently executing node
        self._resume_session = resume_session
        self._resume_checkpoint = resume_checkpoint
        self._session_index: list[str] = []  # IDs from last listing
        self._show_logs: bool = False  # Clean mode by default
        self._log_buffer: list[str] = []  # Buffered log lines for backfill on toggle ON
        self._attached_pdf: dict | None = None  # Pending PDF attachment for next message

        # Dedicated event loop for agent execution.
        # Keeps blocking runtime code (LLM calls, MCP tools) off
        # the Textual event loop so the UI stays responsive.
        self._agent_loop = asyncio.new_event_loop()
        self._agent_thread = threading.Thread(
            target=self._agent_loop.run_forever,
            daemon=True,
            name="agent-execution",
        )
        self._agent_thread.start()

    def compose(self) -> ComposeResult:
        yield RichLog(
            id="chat-history",
            highlight=True,
            markup=True,
            auto_scroll=False,
            wrap=True,
            min_width=0,
        )
        yield RichLog(
            id="streaming-output",
            highlight=True,
            markup=True,
            auto_scroll=True,
            wrap=True,
            min_width=0,
        )
        yield Label("Agent is processing...", id="processing-indicator")
        with Horizontal(id="input-row"):
            yield ChatTextArea(id="chat-input", placeholder="Enter input for agent...")
            yield Button("↵ Send", id="action-button", disabled=True)

    # Regex for file:// URIs that are NOT already inside Rich [link=...] markup
    _FILE_URI_RE = re.compile(r"(?<!\[link=)(file://[^\s)\]>*]+)")

    def _linkify(self, text: str) -> str:
        """Convert bare file:// URIs to clickable Rich [link=...] markup with short display text."""

        def _shorten(match: re.Match) -> str:
            uri = match.group(1)
            filename = uri.rsplit("/", 1)[-1] if "/" in uri else uri
            return f"[link={uri}]{filename}[/link]"

        return self._FILE_URI_RE.sub(_shorten, text)

    def _write_history(self, content: str) -> None:
        """Write to chat history and scroll to bottom."""
        history = self.query_one("#chat-history", RichLog)
        history.write(self._linkify(content))
        history.scroll_end(animate=False)

    def toggle_logs(self) -> None:
        """Toggle inline log display on/off. Backfills buffered logs on toggle ON."""
        self._show_logs = not self._show_logs
        if self._show_logs and self._log_buffer:
            self._write_history("[dim]--- Backfilling logs ---[/dim]")
            for line in self._log_buffer:
                self._write_history(line)
            self._write_history("[dim]--- Live logs ---[/dim]")
        mode = "ON (dirty)" if self._show_logs else "OFF (clean)"
        self._write_history(f"[dim]Logs {mode}[/dim]")

    def write_log_event(self, event: AgentEvent) -> None:
        """Buffer a formatted agent event. Display inline if logs are ON."""
        formatted = format_event(event)
        self._log_buffer.append(formatted)
        if self._show_logs:
            self._write_history(formatted)

    def write_python_log(self, record: logging.LogRecord) -> None:
        """Buffer a formatted Python log record. Display inline if logs are ON."""
        formatted = format_python_log(record)
        self._log_buffer.append(formatted)
        if self._show_logs:
            self._write_history(formatted)

    async def _handle_command(self, command: str) -> None:
        """Handle slash commands for session and checkpoint operations."""
        parts = command.split(maxsplit=2)
        cmd = parts[0].lower()

        if cmd == "/help":
            self._write_history("""[bold cyan]Available Commands:[/bold cyan]
  [bold]/attach[/bold]                      - Open file dialog to attach a PDF
  [bold]/attach[/bold] <file_path>          - Attach a PDF from a specific path
  [bold]/detach[/bold]                      - Remove the currently attached PDF
  [bold]/sessions[/bold]                    - List all sessions for this agent
  [bold]/sessions[/bold] <session_id>       - Show session details and checkpoints
  [bold]/resume[/bold]                      - List sessions and pick one to resume
  [bold]/resume[/bold] <number>             - Resume session by list number
  [bold]/resume[/bold] <session_id>         - Resume session by ID
  [bold]/recover[/bold] <session_id> <cp_id> - Recover from specific checkpoint
  [bold]/pause[/bold]                      - Pause current execution (Ctrl+Z)
  [bold]/agents[/bold]                     - Browse and switch agents (Ctrl+A)
  [bold]/coder[/bold] [reason]             - Escalate to Hive Coder for code changes
  [bold]/back[/bold] [summary]             - Return from Hive Coder to worker agent
  [bold]/graphs[/bold]                     - List loaded graphs and their status
  [bold]/graph[/bold] <id>                 - Switch active graph focus
  [bold]/load[/bold] <path>                - Load an agent graph into the session
  [bold]/unload[/bold] <id>                - Remove a graph from the session
  [bold]/help[/bold]                       - Show this help message

[dim]Examples:[/dim]
  /attach                                [dim]# Open file picker dialog[/dim]
  /attach ~/Documents/report.pdf         [dim]# Attach a specific PDF[/dim]
  /detach                                [dim]# Remove attached PDF[/dim]
  /sessions                              [dim]# List all sessions[/dim]
  /resume 1                              [dim]# Resume first listed session[/dim]
  /graphs                                [dim]# Show loaded agent graphs[/dim]
  /graph email_agent                     [dim]# Switch focus to email_agent[/dim]
  /load exports/email_agent              [dim]# Load agent into session[/dim]
  /unload email_agent                    [dim]# Remove agent from session[/dim]
  /pause                                 [dim]# Pause (or Ctrl+Z)[/dim]
""")
        elif cmd == "/sessions":
            session_id = parts[1].strip() if len(parts) > 1 else None
            await self._cmd_sessions(session_id)
        elif cmd == "/resume":
            if len(parts) < 2:
                # No arg → show session list so user can pick one
                await self._cmd_sessions(None)
                return

            arg = parts[1].strip()

            # Numeric index → resolve from last listing
            if arg.isdigit():
                idx = int(arg) - 1  # 1-based to 0-based
                if 0 <= idx < len(self._session_index):
                    session_id = self._session_index[idx]
                else:
                    self._write_history(f"[bold red]Error:[/bold red] No session at index {arg}")
                    self._write_history("  Use [bold]/resume[/bold] to see available sessions")
                    return
            else:
                session_id = arg

            await self._cmd_resume(session_id)
        elif cmd == "/recover":
            # Recover from specific checkpoint
            if len(parts) < 3:
                self._write_history(
                    "[bold red]Error:[/bold red] /recover requires session_id and checkpoint_id"
                )
                self._write_history("  Usage: [bold]/recover <session_id> <checkpoint_id>[/bold]")
                self._write_history(
                    "  Tip: Use [bold]/sessions <session_id>[/bold] to see checkpoints"
                )
                return
            session_id = parts[1].strip()
            checkpoint_id = parts[2].strip()
            await self._cmd_recover(session_id, checkpoint_id)
        elif cmd == "/attach":
            file_path = parts[1].strip() if len(parts) > 1 else None
            await self._cmd_attach(file_path)
        elif cmd == "/detach":
            if self._attached_pdf:
                name = self._attached_pdf["filename"]
                self._attached_pdf = None
                self._write_history(f"[dim]Detached: {name}[/dim]")
            else:
                self._write_history("[dim]No PDF attached.[/dim]")
        elif cmd == "/pause":
            await self._cmd_pause()
        elif cmd == "/agents":
            app = self.app
            if hasattr(app, "action_show_agent_picker"):
                await app.action_show_agent_picker()
        elif cmd == "/graphs":
            self._cmd_graphs()
        elif cmd == "/graph":
            if len(parts) < 2:
                self._write_history("[bold red]Usage:[/bold red] /graph <graph_id>")
            else:
                self._cmd_switch_graph(parts[1].strip())
        elif cmd == "/load":
            if len(parts) < 2:
                self._write_history("[bold red]Usage:[/bold red] /load <agent_path>")
            else:
                await self._cmd_load_graph(parts[1].strip())
        elif cmd == "/unload":
            if len(parts) < 2:
                self._write_history("[bold red]Usage:[/bold red] /unload <graph_id>")
            else:
                await self._cmd_unload_graph(parts[1].strip())
        elif cmd == "/coder":
            reason = " ".join(parts[1:]) if len(parts) > 1 else ""
            await self._cmd_coder(reason)
        elif cmd == "/back":
            summary = " ".join(parts[1:]) if len(parts) > 1 else ""
            await self._cmd_back(summary)
        else:
            self._write_history(
                f"[bold red]Unknown command:[/bold red] {cmd}\n"
                "Type [bold]/help[/bold] for available commands"
            )

    def attach_pdf(self, path: Path) -> None:
        """Validate and stage a PDF file for the next message.

        Copies the PDF to ~/.hive/assets/ and stores the path. The agent's
        pdf_read tool handles text extraction at runtime.

        Called by /attach <path> or by the native file dialog.
        """
        path = Path(path).expanduser().resolve()

        if not path.exists():
            self._write_history(f"[bold red]Error:[/bold red] File not found: {path}")
            return
        if path.suffix.lower() != ".pdf":
            self._write_history("[bold red]Error:[/bold red] Only PDF files are supported")
            return

        # Copy to ~/.hive/assets/, deduplicating like a normal filesystem:
        # resume.pdf → resume(1).pdf → resume(2).pdf
        assets_dir = Path.home() / ".hive" / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        dest = assets_dir / path.name
        counter = 1
        while dest.exists():
            dest = assets_dir / f"{path.stem}({counter}){path.suffix}"
            counter += 1
        shutil.copy2(path, dest)

        self._attached_pdf = {
            "filename": path.name,
            "path": str(dest),
        }

        self._write_history(f"[green]Attached:[/green] {path.name}")
        self._write_history("[dim]PDF will be read by the agent on your next message.[/dim]")

    async def _cmd_attach(self, file_path: str | None = None) -> None:
        """Attach a PDF file for context injection into the next message."""
        if file_path is None:
            from framework.tui.widgets.file_browser import _has_gui, pick_pdf_file

            if not _has_gui():
                self._write_history(
                    "[bold yellow]No GUI available.[/bold yellow] "
                    "Provide a path: [bold]/attach /path/to/file.pdf[/bold]"
                )
                return

            self._write_history("[dim]Opening file dialog...[/dim]")
            path = await pick_pdf_file()

            if path is not None:
                self.attach_pdf(path)
            return

        self.attach_pdf(Path(file_path))

    async def _cmd_sessions(self, session_id: str | None) -> None:
        """List sessions or show details of a specific session."""
        try:
            # Get storage path from runtime
            storage_path = self.runtime._storage.base_path

            if session_id:
                # Show details of specific session including checkpoints
                await self._show_session_details(storage_path, session_id)
            else:
                # List all sessions
                await self._list_sessions(storage_path)
        except Exception as e:
            self._write_history(f"[bold red]Error:[/bold red] {e}")
            self._write_history("  Could not access session data")

    async def _find_latest_resumable_session(self) -> str | None:
        """Find the most recent paused or failed session."""
        try:
            storage_path = self.runtime._storage.base_path
            sessions_dir = storage_path / "sessions"

            if not sessions_dir.exists():
                return None

            # Get all sessions, most recent first
            session_dirs = sorted(
                [d for d in sessions_dir.iterdir() if d.is_dir()],
                key=lambda d: d.name,
                reverse=True,
            )

            # Find first paused, failed, or cancelled session
            import json

            for session_dir in session_dirs:
                state_file = session_dir / "state.json"
                if not state_file.exists():
                    continue

                with open(state_file) as f:
                    state = json.load(f)

                status = state.get("status", "").lower()

                # Check if resumable (any non-completed status)
                if status in ["paused", "failed", "cancelled", "active"]:
                    return session_dir.name

            return None
        except Exception:
            return None

    def _get_session_label(self, state: dict) -> str:
        """Extract the first user message from input_data as a human-readable label."""
        input_data = state.get("input_data", {})
        for value in input_data.values():
            if isinstance(value, str) and value.strip():
                label = value.strip()
                return label[:60] + "..." if len(label) > 60 else label
        return "(no input)"

    async def _list_sessions(self, storage_path: Path) -> None:
        """List all sessions for the agent."""
        self._write_history("[bold cyan]Available Sessions:[/bold cyan]")

        # Find all session directories
        sessions_dir = storage_path / "sessions"
        if not sessions_dir.exists():
            self._write_history("[dim]No sessions found.[/dim]")
            self._write_history("  Sessions will appear here after running the agent")
            return

        session_dirs = sorted(
            [d for d in sessions_dir.iterdir() if d.is_dir()],
            key=lambda d: d.name,
            reverse=True,  # Most recent first
        )

        if not session_dirs:
            self._write_history("[dim]No sessions found.[/dim]")
            return

        self._write_history(f"[dim]Found {len(session_dirs)} session(s)[/dim]\n")

        # Reset the session index for numeric lookups
        self._session_index = []

        import json

        for session_dir in session_dirs[:10]:  # Show last 10 sessions
            session_id = session_dir.name
            state_file = session_dir / "state.json"

            if not state_file.exists():
                continue

            # Read session state
            try:
                with open(state_file) as f:
                    state = json.load(f)

                # Track this session for /resume <number> lookup
                self._session_index.append(session_id)
                index = len(self._session_index)

                status = state.get("status", "unknown").upper()
                label = self._get_session_label(state)

                # Status with color
                if status == "COMPLETED":
                    status_colored = f"[green]{status}[/green]"
                elif status == "FAILED":
                    status_colored = f"[red]{status}[/red]"
                elif status == "PAUSED":
                    status_colored = f"[yellow]{status}[/yellow]"
                elif status == "CANCELLED":
                    status_colored = f"[dim yellow]{status}[/dim yellow]"
                else:
                    status_colored = f"[dim]{status}[/dim]"

                # Session line with index and label
                self._write_history(f"  [bold]{index}.[/bold] {label}  {status_colored}")
                self._write_history(f"     [dim]{session_id}[/dim]")
                self._write_history("")  # Blank line

            except Exception as e:
                self._write_history(f"   [dim red]Error reading: {e}[/dim red]")

        if self._session_index:
            self._write_history("[dim]Use [bold]/resume <number>[/bold] to resume a session[/dim]")

    async def _show_session_details(self, storage_path: Path, session_id: str) -> None:
        """Show detailed information about a specific session."""
        self._write_history(f"[bold cyan]Session Details:[/bold cyan] {session_id}\n")

        session_dir = storage_path / "sessions" / session_id
        if not session_dir.exists():
            self._write_history("[bold red]Error:[/bold red] Session not found")
            self._write_history(f"  Path: {session_dir}")
            self._write_history("  Tip: Use [bold]/sessions[/bold] to see available sessions")
            return

        state_file = session_dir / "state.json"
        if not state_file.exists():
            self._write_history("[bold red]Error:[/bold red] Session state not found")
            return

        try:
            import json

            with open(state_file) as f:
                state = json.load(f)

            # Basic info
            status = state.get("status", "unknown").upper()
            if status == "COMPLETED":
                status_colored = f"[green]{status}[/green]"
            elif status == "FAILED":
                status_colored = f"[red]{status}[/red]"
            elif status == "PAUSED":
                status_colored = f"[yellow]{status}[/yellow]"
            elif status == "CANCELLED":
                status_colored = f"[dim yellow]{status}[/dim yellow]"
            else:
                status_colored = status

            self._write_history(f"Status: {status_colored}")

            if "started_at" in state:
                self._write_history(f"Started: {state['started_at']}")
            if "completed_at" in state:
                self._write_history(f"Completed: {state['completed_at']}")

            # Execution path
            if "execution_path" in state and state["execution_path"]:
                self._write_history("\n[bold]Execution Path:[/bold]")
                for node_id in state["execution_path"]:
                    self._write_history(f"  ✓ {node_id}")

            # Checkpoints
            checkpoint_dir = session_dir / "checkpoints"
            if checkpoint_dir.exists():
                checkpoint_files = sorted(checkpoint_dir.glob("cp_*.json"))
                if checkpoint_files:
                    self._write_history(
                        f"\n[bold]Available Checkpoints:[/bold] ({len(checkpoint_files)})"
                    )

                    # Load and show checkpoints
                    for i, cp_file in enumerate(checkpoint_files[-5:], 1):  # Last 5
                        try:
                            with open(cp_file) as f:
                                cp_data = json.load(f)

                            cp_id = cp_data.get("checkpoint_id", cp_file.stem)
                            cp_type = cp_data.get("checkpoint_type", "unknown")
                            current_node = cp_data.get("current_node", "unknown")
                            is_clean = cp_data.get("is_clean", False)

                            clean_marker = "✓" if is_clean else "⚠"
                            self._write_history(f"  {i}. {clean_marker} [cyan]{cp_id}[/cyan]")
                            self._write_history(f"     Type: {cp_type}, Node: {current_node}")
                        except Exception:
                            pass

            # Quick actions
            if checkpoint_dir.exists() and list(checkpoint_dir.glob("cp_*.json")):
                self._write_history("\n[bold]Quick Actions:[/bold]")
                self._write_history(
                    f"  [dim]/resume {session_id}[/dim]  - Resume from latest checkpoint"
                )

        except Exception as e:
            self._write_history(f"[bold red]Error:[/bold red] {e}")
            import traceback

            self._write_history(f"[dim]{traceback.format_exc()}[/dim]")

    async def _cmd_resume(self, session_id: str) -> None:
        """Resume a session from its last state (session state, not checkpoint)."""
        try:
            storage_path = self.runtime._storage.base_path
            session_dir = storage_path / "sessions" / session_id

            # Verify session exists
            if not session_dir.exists():
                self._write_history(f"[bold red]Error:[/bold red] Session not found: {session_id}")
                self._write_history("  Use [bold]/sessions[/bold] to see available sessions")
                return

            # Load session state
            state_file = session_dir / "state.json"
            if not state_file.exists():
                self._write_history("[bold red]Error:[/bold red] Session state not found")
                return

            import json

            with open(state_file) as f:
                state = json.load(f)

            # Resume from session state (not checkpoint)
            progress = state.get("progress", {})
            paused_at = progress.get("paused_at") or progress.get("resume_from")

            if paused_at:
                # Has paused_at - resume from there
                resume_session_state = {
                    "resume_session_id": session_id,
                    "paused_at": paused_at,
                    "memory": state.get("memory", {}),
                    "execution_path": progress.get("path", []),
                    "node_visit_counts": progress.get("node_visit_counts", {}),
                }
                resume_info = f"From node: [cyan]{paused_at}[/cyan]"
            else:
                # No paused_at - retry with same input but reuse session directory
                resume_session_state = {
                    "resume_session_id": session_id,
                    "memory": state.get("memory", {}),
                    "execution_path": progress.get("path", []),
                    "node_visit_counts": progress.get("node_visit_counts", {}),
                }
                resume_info = "Retrying with same input"

            # Display resume info
            self._write_history(f"[bold cyan]🔄 Resuming session[/bold cyan] {session_id}")
            self._write_history(f"   {resume_info}")
            if paused_at:
                self._write_history("   [dim](Using session state, not checkpoint)[/dim]")

            # Check if already executing
            if self._current_exec_id is not None:
                self._write_history(
                    "[bold yellow]Warning:[/bold yellow] An execution is already running"
                )
                self._write_history("  Wait for it to complete or use /pause first")
                return

            # Get original input data from session state
            input_data = state.get("input_data", {})

            # Show indicator
            indicator = self.query_one("#processing-indicator", Label)
            indicator.update("Resuming from session state...")
            indicator.display = True

            # Update placeholder
            chat_input = self.query_one("#chat-input", ChatTextArea)
            chat_input.placeholder = "Commands: /pause, /sessions (agent resuming...)"

            # Trigger execution with resume state
            try:
                entry_points = self.runtime.get_entry_points()
                if not entry_points:
                    self._write_history("[bold red]Error:[/bold red] No entry points available")
                    return

                # Submit execution with resume state and original input data
                future = asyncio.run_coroutine_threadsafe(
                    self.runtime.trigger(
                        entry_points[0].id,
                        input_data=input_data,
                        session_state=resume_session_state,
                    ),
                    self._agent_loop,
                )
                exec_id = await asyncio.wrap_future(future)
                self._current_exec_id = exec_id

                self._write_history(
                    f"[green]✓[/green] Resume started (execution: {exec_id[:12]}...)"
                )
                self._write_history("  Agent is continuing from where it stopped...")
                # Enable Pause button now that execution is running
                self._set_button_pause_mode()

            except Exception as e:
                self._write_history(f"[bold red]Error starting resume:[/bold red] {e}")
                indicator.display = False
                chat_input.placeholder = "Enter input for agent..."

        except Exception as e:
            self._write_history(f"[bold red]Error:[/bold red] {e}")
            import traceback

            self._write_history(f"[dim]{traceback.format_exc()}[/dim]")

    async def _cmd_recover(self, session_id: str, checkpoint_id: str) -> None:
        """Recover a session from a specific checkpoint (time-travel debugging)."""
        try:
            storage_path = self.runtime._storage.base_path
            session_dir = storage_path / "sessions" / session_id

            # Verify session exists
            if not session_dir.exists():
                self._write_history(f"[bold red]Error:[/bold red] Session not found: {session_id}")
                self._write_history("  Use [bold]/sessions[/bold] to see available sessions")
                return

            # Verify checkpoint exists
            checkpoint_file = session_dir / "checkpoints" / f"{checkpoint_id}.json"
            if not checkpoint_file.exists():
                self._write_history(
                    f"[bold red]Error:[/bold red] Checkpoint not found: {checkpoint_id}"
                )
                self._write_history(
                    f"  Use [bold]/sessions {session_id}[/bold] to see available checkpoints"
                )
                return

            # Display recover info
            self._write_history(f"[bold cyan]⏪ Recovering session[/bold cyan] {session_id}")
            self._write_history(f"   From checkpoint: [cyan]{checkpoint_id}[/cyan]")
            self._write_history(
                "   [dim](Checkpoint-based recovery for time-travel debugging)[/dim]"
            )

            # Check if already executing
            if self._current_exec_id is not None:
                self._write_history(
                    "[bold yellow]Warning:[/bold yellow] An execution is already running"
                )
                self._write_history("  Wait for it to complete or use /pause first")
                return

            # Create session_state for checkpoint recovery
            recover_session_state = {
                "resume_session_id": session_id,
                "resume_from_checkpoint": checkpoint_id,
            }

            # Show indicator
            indicator = self.query_one("#processing-indicator", Label)
            indicator.update("Recovering from checkpoint...")
            indicator.display = True

            # Update placeholder
            chat_input = self.query_one("#chat-input", ChatTextArea)
            chat_input.placeholder = "Commands: /pause, /sessions (agent recovering...)"

            # Trigger execution with checkpoint recovery
            try:
                entry_points = self.runtime.get_entry_points()
                if not entry_points:
                    self._write_history("[bold red]Error:[/bold red] No entry points available")
                    return

                # Submit execution with checkpoint recovery state
                future = asyncio.run_coroutine_threadsafe(
                    self.runtime.trigger(
                        entry_points[0].id,
                        input_data={},
                        session_state=recover_session_state,
                    ),
                    self._agent_loop,
                )
                exec_id = await asyncio.wrap_future(future)
                self._current_exec_id = exec_id

                self._write_history(
                    f"[green]✓[/green] Recovery started (execution: {exec_id[:12]}...)"
                )
                self._write_history("  Agent is continuing from checkpoint...")
                # Enable Pause button now that execution is running
                self._set_button_pause_mode()

            except Exception as e:
                self._write_history(f"[bold red]Error starting recovery:[/bold red] {e}")
                indicator.display = False
                chat_input.placeholder = "Enter input for agent..."

        except Exception as e:
            self._write_history(f"[bold red]Error:[/bold red] {e}")
            import traceback

            self._write_history(f"[dim]{traceback.format_exc()}[/dim]")

    async def _cmd_pause(self) -> None:
        """Immediately pause execution by cancelling task (same as Ctrl+Z)."""
        # Check if there's a current execution
        if not self._current_exec_id:
            self._write_history("[bold yellow]No active execution to pause[/bold yellow]")
            self._write_history("  Start an execution first, then use /pause during execution")
            return

        # Find and cancel the execution task - executor will catch and save state
        task_cancelled = False
        for stream in self.runtime._streams.values():
            exec_id = self._current_exec_id
            task = stream._execution_tasks.get(exec_id)
            if task and not task.done():
                task.cancel()
                task_cancelled = True
                self._write_history("[bold green]⏸ Execution paused - state saved[/bold green]")
                self._write_history("  Resume later with: [bold]/resume[/bold]")
                break

        if not task_cancelled:
            self._write_history("[bold yellow]Execution already completed[/bold yellow]")

    async def _cmd_coder(self, reason: str = "") -> None:
        """User-initiated escalation to Hive Coder."""
        app = self.app
        if not hasattr(app, "_do_escalate_to_coder"):
            self._write_history("[bold red]Escalation not available[/bold red]")
            return

        context_parts = []
        if self._active_node_id:
            context_parts.append(f"Active node: {self._active_node_id}")
        if self._streaming_snapshot:
            snippet = self._streaming_snapshot[:500]
            context_parts.append(f"Last agent output: {snippet}")
        context = "\n".join(context_parts)

        if not reason:
            reason = "User-initiated escalation via /coder"

        self._write_history("[bold cyan]Escalating to Hive Coder...[/bold cyan]")

        node_id = self._input_node_id or self._active_node_id or ""
        app._do_escalate_to_coder(
            reason=reason,
            context=context,
            node_id=node_id,
        )

    async def _cmd_back(self, summary: str = "") -> None:
        """Return from Hive Coder to the worker agent."""
        app = self.app
        if not hasattr(app, "_escalation_stack"):
            self._write_history("[bold yellow]Not in an escalation.[/bold yellow]")
            return
        if not app._escalation_stack:
            self._write_history(
                "[bold yellow]Not in an escalation.[/bold yellow] "
                "/back is only available after /coder or agent escalation."
            )
            return

        self._write_history("[bold cyan]Returning to worker agent...[/bold cyan]")
        await app._return_from_escalation(summary)

    def _cmd_graphs(self) -> None:
        """List all loaded graphs and their status."""
        graphs = self.runtime.list_graphs()
        if not graphs:
            self._write_history("[dim]No graphs loaded[/dim]")
            return

        lines = ["[bold cyan]Loaded Graphs:[/bold cyan]"]
        for gid in graphs:
            reg = self.runtime.get_graph_registration(gid)
            if reg is None:
                continue
            is_primary = gid == self.runtime.graph_id
            is_active = gid == self.runtime.active_graph_id
            markers = []
            if is_primary:
                markers.append("primary")
            if is_active:
                markers.append("active")
            marker_str = f" [dim]({', '.join(markers)})[/dim]" if markers else ""
            ep_list = ", ".join(reg.entry_points.keys())
            active_execs = sum(len(s.active_execution_ids) for s in reg.streams.values())
            exec_str = f" [green]{active_execs} running[/green]" if active_execs else ""
            lines.append(f"  [bold]{gid}[/bold]{marker_str} — eps: {ep_list}{exec_str}")
        self._write_history("\n".join(lines))

    def _cmd_switch_graph(self, graph_id: str) -> None:
        """Switch the active graph focus."""
        try:
            self.runtime.active_graph_id = graph_id
        except ValueError:
            self._write_history(
                f"[bold red]Graph '{graph_id}' not found.[/bold red] "
                "Use /graphs to see loaded graphs."
            )
            return

        # Tell the app to update the UI
        app = self.app
        if hasattr(app, "action_switch_graph"):
            app.action_switch_graph(graph_id)
        else:
            self._write_history(f"[bold green]Switched to graph: {graph_id}[/bold green]")

    async def _cmd_load_graph(self, agent_path: str) -> None:
        """Load an agent graph into the session."""
        from pathlib import Path

        path = Path(agent_path).resolve()
        if not path.exists():
            self._write_history(f"[bold red]Path does not exist:[/bold red] {path}")
            return

        self._write_history(f"[dim]Loading agent from {path}...[/dim]")

        try:
            from framework.runner.runner import AgentRunner

            graph_id = await AgentRunner.setup_as_secondary(path, self.runtime)
            self._write_history(
                f"[bold green]Loaded graph '{graph_id}'[/bold green] — "
                "use /graphs to see all, /graph to switch"
            )
        except Exception as e:
            self._write_history(f"[bold red]Failed to load agent:[/bold red] {e}")

    async def _cmd_unload_graph(self, graph_id: str) -> None:
        """Unload a secondary graph from the session."""
        try:
            await self.runtime.remove_graph(graph_id)
            self._write_history(f"[bold green]Unloaded graph '{graph_id}'[/bold green]")
        except ValueError as e:
            self._write_history(f"[bold red]Error:[/bold red] {e}")

    def _node_label(self, node_id: str | None = None) -> str:
        """Resolve a node_id to a Rich-formatted speaker label."""
        nid = node_id or self._active_node_id
        if nid:
            node = self.runtime.graph.get_node(nid)
            name = node.name if node else nid
            return f"[bold blue]{name}:[/bold blue]"
        return "[bold blue]Agent:[/bold blue]"

    def _clear_streaming(self) -> None:
        """Reset streaming state and hide the live output area."""
        self._streaming_snapshot = ""
        self._streaming_written = 0
        stream_log = self.query_one("#streaming-output", RichLog)
        stream_log.clear()
        stream_log.display = False
        # Hiding the streaming pane makes chat-history taller (1fr reclaims
        # the space).  Re-scroll so subsequent _write_history calls see
        # is_vertical_scroll_end == True.
        self.query_one("#chat-history", RichLog).scroll_end(animate=False)

    def flush_streaming(self) -> None:
        """Flush any accumulated streaming text to history.

        Called by the app when switching graphs to ensure in-progress
        streaming content is preserved before the UI context changes.
        """
        if self._streaming_snapshot:
            self._write_history(f"{self._node_label()} {self._streaming_snapshot}")
            self._clear_streaming()

    def on_mount(self) -> None:
        """Add welcome message and check for resumable sessions."""
        history = self.query_one("#chat-history", RichLog)
        history.write(
            "[bold cyan]Chat REPL Ready[/bold cyan] — "
            "Type your input or use [bold]/help[/bold] for commands\n"
        )

        # Auto-trigger resume/recover if CLI args provided
        if self._resume_session:
            if self._resume_checkpoint:
                # Use /recover for checkpoint-based recovery
                history.write(
                    "\n[bold cyan]🔄 Auto-recovering from checkpoint "
                    "(--resume-session + --checkpoint)[/bold cyan]"
                )
                self.call_later(self._cmd_recover, self._resume_session, self._resume_checkpoint)
            else:
                # Use /resume for session state resume
                history.write(
                    "\n[bold cyan]🔄 Auto-resuming session (--resume-session)[/bold cyan]"
                )
                self.call_later(self._cmd_resume, self._resume_session)
            return  # Skip normal startup messages

        # Check for resumable sessions
        self._check_and_show_resumable_sessions()

        # Show agent intro message if available
        if self.runtime.intro_message:
            history.write(f"[bold blue]Agent:[/bold blue] {self.runtime.intro_message}\n")
        else:
            history.write(
                "[dim]Quick start: /sessions to see previous sessions, "
                "/pause to pause execution[/dim]\n"
            )

    def _check_and_show_resumable_sessions(self) -> None:
        """Check for non-terminated sessions and prompt user."""
        try:
            storage_path = self.runtime._storage.base_path
            sessions_dir = storage_path / "sessions"

            if not sessions_dir.exists():
                return

            # Find non-terminated sessions (paused, failed, cancelled, active)
            resumable = []
            session_dirs = sorted(
                [d for d in sessions_dir.iterdir() if d.is_dir()],
                key=lambda d: d.name,
                reverse=True,  # Most recent first
            )

            import json

            for session_dir in session_dirs[:5]:  # Check last 5 sessions
                state_file = session_dir / "state.json"
                if not state_file.exists():
                    continue

                try:
                    with open(state_file) as f:
                        state = json.load(f)

                    status = state.get("status", "").lower()
                    # Non-terminated statuses
                    if status in ["paused", "failed", "cancelled", "active"]:
                        resumable.append(
                            {
                                "session_id": session_dir.name,
                                "status": status.upper(),
                                "label": self._get_session_label(state),
                            }
                        )
                except Exception:
                    continue

            if resumable:
                # Populate session index so /resume <number> works immediately
                self._session_index = [s["session_id"] for s in resumable[:3]]

                self._write_history("\n[bold yellow]Non-terminated sessions found:[/bold yellow]")
                for i, session in enumerate(resumable[:3], 1):  # Show top 3
                    status = session["status"]
                    label = session["label"]

                    # Color code status
                    if status == "PAUSED":
                        status_colored = f"[yellow]{status}[/yellow]"
                    elif status == "FAILED":
                        status_colored = f"[red]{status}[/red]"
                    elif status == "CANCELLED":
                        status_colored = f"[dim yellow]{status}[/dim yellow]"
                    else:
                        status_colored = f"[dim]{status}[/dim]"

                    self._write_history(f"  [bold]{i}.[/bold] {label}  {status_colored}")

                self._write_history("\n  Type [bold]/resume <number>[/bold] to continue a session")
                self._write_history("  Or just type your input to start a new session\n")

        except Exception:
            # Silently fail - don't block TUI startup
            pass

    def _set_button_send_mode(self) -> None:
        """Switch the action button to Send mode (green arrow)."""
        try:
            btn = self.query_one("#action-button", Button)
            btn.label = "↵ Send"
            btn.disabled = False
            btn.remove_class("pause-mode")
            btn.add_class("send-mode")
        except Exception:
            pass

    def _set_button_pause_mode(self) -> None:
        """Switch the action button to Pause mode (red pause)."""
        try:
            btn = self.query_one("#action-button", Button)
            btn.label = "⏸ Pause"
            btn.disabled = False
            btn.remove_class("send-mode")
            btn.add_class("pause-mode")
        except Exception:
            pass

    def _set_button_idle_mode(self) -> None:
        """Switch the action button to idle/disabled state."""
        try:
            btn = self.query_one("#action-button", Button)
            btn.label = "↵ Send"
            btn.disabled = True
            btn.remove_class("pause-mode")
            btn.add_class("send-mode")
        except Exception:
            pass

    async def on_chat_text_area_submitted(self, message: ChatTextArea.Submitted) -> None:
        """Handle chat input submission."""
        await self._submit_input(message.text)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Toggle the Send button based on whether there is text in the input."""
        if event.text_area.id != "chat-input":
            return
        # Only update button if we're not currently executing (Pause takes priority)
        if self._current_exec_id is not None:
            return
        has_text = bool(event.text_area.text.strip())
        if has_text:
            self._set_button_send_mode()
        else:
            self._set_button_idle_mode()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle action button click — Send when idle, Pause when executing."""
        if event.button.id != "action-button":
            return
        if self._current_exec_id is not None:
            # Execution running → act as Pause
            await self._cmd_pause()
        else:
            # No execution → act as Send (submit whatever is in the input)
            chat_input = self.query_one("#chat-input", ChatTextArea)
            text = chat_input.text.strip()
            if text:
                chat_input.clear()
                await self._submit_input(text)

    async def _submit_input(self, user_input: str) -> None:
        """Handle submitted text — either start new execution or inject input."""
        if not user_input:
            return

        # Handle commands (starting with /) - ALWAYS process commands first
        # Commands work during execution, during client-facing input, anytime
        if user_input.startswith("/"):
            await self._handle_command(user_input)
            return

        # Client-facing input: route to the waiting node
        if self._waiting_for_input and self._input_node_id:
            self._write_history(f"[bold green]You:[/bold green] {user_input}")

            # Keep input enabled for commands (but change placeholder)
            chat_input = self.query_one("#chat-input", ChatTextArea)
            chat_input.placeholder = "Commands: /pause, /sessions (agent processing...)"
            self._waiting_for_input = False

            indicator = self.query_one("#processing-indicator", Label)
            indicator.update("Thinking...")

            node_id = self._input_node_id
            graph_id = self._input_graph_id
            self._input_node_id = None
            self._input_graph_id = None

            try:
                future = asyncio.run_coroutine_threadsafe(
                    self.runtime.inject_input(node_id, user_input, graph_id=graph_id),
                    self._agent_loop,
                )
                await asyncio.wrap_future(future)
            except Exception as e:
                self._write_history(f"[bold red]Error delivering input:[/bold red] {e}")
            return

        # Mid-execution input: inject into the active node's conversation
        if self._current_exec_id is not None and self._active_node_id:
            self._write_history(f"[bold green]You:[/bold green] {user_input}")
            node_id = self._active_node_id
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self.runtime.inject_input(node_id, user_input),
                    self._agent_loop,
                )
                await asyncio.wrap_future(future)
            except Exception as e:
                self._write_history(f"[bold red]Error delivering input:[/bold red] {e}")
            return

        # Double-submit guard: no active node to inject into
        if self._current_exec_id is not None:
            self._write_history("[dim]Agent is still running — please wait.[/dim]")
            return

        indicator = self.query_one("#processing-indicator", Label)

        # Append user message
        self._write_history(f"[bold green]You:[/bold green] {user_input}")

        try:
            # Get entry point
            entry_points = self.runtime.get_entry_points()
            if not entry_points:
                self._write_history("[bold red]Error:[/bold red] No entry points")
                return

            # Determine the input key from the entry node
            entry_point = entry_points[0]
            entry_node = self.runtime.graph.get_node(entry_point.entry_node)

            if entry_node and entry_node.input_keys:
                input_key = entry_node.input_keys[0]
            else:
                input_key = "input"

            # Reset streaming state
            self._clear_streaming()

            # Show processing indicator
            indicator.update("Thinking...")
            indicator.display = True

            # Switch button to Pause mode
            self._set_button_pause_mode()

            # Keep input enabled for commands during execution
            chat_input = self.query_one("#chat-input", ChatTextArea)
            chat_input.placeholder = "Commands available: /pause, /sessions, /help"

            # Build input data, injecting attached PDF file path if present
            input_data = {input_key: user_input}
            if self._attached_pdf:
                input_data["pdf_file_path"] = self._attached_pdf["path"]
                self._write_history(f"[dim]Including PDF: {self._attached_pdf['filename']}[/dim]")
                self._attached_pdf = None

            # Submit execution to the dedicated agent loop so blocking
            # runtime code (LLM, MCP tools) never touches Textual's loop.
            # trigger() returns immediately with an exec_id; the heavy
            # execution task runs entirely on the agent thread.
            future = asyncio.run_coroutine_threadsafe(
                self.runtime.trigger(
                    entry_point_id=entry_point.id,
                    input_data=input_data,
                ),
                self._agent_loop,
            )
            # wrap_future lets us await without blocking Textual's loop
            self._current_exec_id = await asyncio.wrap_future(future)

        except Exception as e:
            indicator.display = False
            self._current_exec_id = None
            # Re-enable input on error
            chat_input = self.query_one("#chat-input", ChatTextArea)
            chat_input.disabled = False
            self._write_history(f"[bold red]Error:[/bold red] {e}")

    # -- Event handlers called by app.py _handle_event --

    def handle_node_started(self, node_id: str) -> None:
        """Reset streaming state and track active node when a new node begins.

        Flushes any stale ``_streaming_snapshot`` left over from the
        previous node and resets the processing indicator so the user
        sees a clean transition between graph nodes.
        """
        # Flush stale snapshot with the PREVIOUS node's label before switching
        if self._streaming_snapshot:
            self._write_history(f"{self._node_label()} {self._streaming_snapshot}")
        self._clear_streaming()
        self._active_node_id = node_id
        indicator = self.query_one("#processing-indicator", Label)
        indicator.update("Thinking...")

    def handle_loop_iteration(self, iteration: int) -> None:
        """Flush accumulated streaming text when a new loop iteration starts."""
        if self._streaming_snapshot:
            self._write_history(f"{self._node_label()} {self._streaming_snapshot}")
        self._clear_streaming()

    def handle_text_delta(self, content: str, snapshot: str) -> None:
        """Handle a streaming text token from the LLM."""
        self._streaming_snapshot = snapshot

        # Stream into the live output area
        stream_log = self.query_one("#streaming-output", RichLog)
        if not stream_log.display:
            stream_log.display = True
            # Showing the streaming pane shrinks chat-history (height: 1fr).
            # Re-scroll so _write_history still sees is_vertical_scroll_end.
            self.query_one("#chat-history", RichLog).scroll_end(animate=False)

        # Rewrite the full snapshot as a single block so text wraps
        # naturally instead of one token per line.
        stream_log.clear()
        stream_log.write(Text.from_markup(f"{self._node_label()} {snapshot}"))
        self._streaming_written = len(snapshot)

    def handle_tool_started(self, tool_name: str, tool_input: dict[str, Any]) -> None:
        """Handle a tool call starting."""
        # Flush any accumulated LLM text before the tool call starts.
        # Without this, text from a turn that also issues tool calls
        # would sit in _streaming_snapshot and get overwritten by the
        # next LLM turn, never appearing in the chat log.
        if self._streaming_snapshot:
            self._write_history(f"{self._node_label()} {self._streaming_snapshot}")
            self._clear_streaming()

        indicator = self.query_one("#processing-indicator", Label)

        if tool_name == "ask_user":
            # Stash the question for handle_input_requested() to display.
            # Suppress the generic "Tool: ask_user" line.
            self._pending_ask_question = tool_input.get("question", "")
            indicator.update("Preparing question...")
            return

        if tool_name == "escalate_to_coder":
            indicator.update("Escalating to coder...")
            return

        # Update indicator to show tool activity
        indicator.update(f"Using tool: {tool_name}...")

        # Buffer and conditionally display tool status line
        line = f"[dim]Tool: {tool_name}[/dim]"
        self._log_buffer.append(line)
        if self._show_logs:
            self._write_history(line)

    def handle_tool_completed(self, tool_name: str, result: str, is_error: bool) -> None:
        """Handle a tool call completing."""
        if tool_name in ("ask_user", "escalate_to_coder"):
            return

        result_str = str(result)
        preview = result_str[:200] + "..." if len(result_str) > 200 else result_str
        preview = preview.replace("\n", " ")

        if is_error:
            line = f"[dim red]Tool {tool_name} error: {preview}[/dim red]"
        else:
            line = f"[dim]Tool {tool_name} result: {preview}[/dim]"
        self._log_buffer.append(line)
        if self._show_logs:
            self._write_history(line)

        # Restore thinking indicator
        indicator = self.query_one("#processing-indicator", Label)
        indicator.update("Thinking...")

    def handle_execution_completed(self, output: dict[str, Any]) -> None:
        """Handle execution finishing successfully."""
        indicator = self.query_one("#processing-indicator", Label)
        indicator.update("")
        indicator.display = False

        # Write the final streaming snapshot to permanent history (if any)
        if self._streaming_snapshot:
            self._write_history(f"{self._node_label()} {self._streaming_snapshot}")
        else:
            output_str = str(output.get("output_string", output))
            self._write_history(f"{self._node_label()} {output_str}")
        self._write_history("")  # separator

        self._current_exec_id = None
        self._clear_streaming()
        self._waiting_for_input = False
        self._input_node_id = None
        self._active_node_id = None
        self._pending_ask_question = ""
        self._log_buffer.clear()

        # Reset button to idle/send mode
        self._set_button_idle_mode()

        # Re-enable input
        chat_input = self.query_one("#chat-input", ChatTextArea)
        chat_input.disabled = False
        chat_input.placeholder = "Enter input for agent..."
        chat_input.focus()

    def handle_execution_failed(self, error: str) -> None:
        """Handle execution failing."""
        indicator = self.query_one("#processing-indicator", Label)
        indicator.update("")
        indicator.display = False

        self._write_history(f"[bold red]Error:[/bold red] {error}")
        self._write_history("")  # separator

        self._current_exec_id = None
        self._clear_streaming()
        self._waiting_for_input = False
        self._pending_ask_question = ""
        self._input_node_id = None
        self._active_node_id = None
        self._log_buffer.clear()

        # Reset button to idle/send mode
        self._set_button_idle_mode()

        # Re-enable input
        chat_input = self.query_one("#chat-input", ChatTextArea)
        chat_input.disabled = False
        chat_input.placeholder = "Enter input for agent..."
        chat_input.focus()

    def handle_escalation_requested(self, data: dict) -> None:
        """Display escalation request from the worker agent."""
        if self._streaming_snapshot:
            self._write_history(f"{self._node_label()} {self._streaming_snapshot}")
            self._clear_streaming()

        reason = data.get("reason", "")
        self._write_history("[bold yellow]Agent is escalating to Hive Coder[/bold yellow]")
        if reason:
            self._write_history(f"[dim]Reason: {reason}[/dim]")

    def handle_input_requested(self, node_id: str, graph_id: str | None = None) -> None:
        """Handle a client-facing node requesting user input.

        Transitions to 'waiting for input' state: flushes the current
        streaming snapshot to history, re-enables the input widget,
        and sets a flag so the next submission routes to inject_input().
        """
        # Flush accumulated streaming text as agent output
        label = self._node_label(node_id)
        flushed_snapshot = self._streaming_snapshot
        if flushed_snapshot:
            self._write_history(f"{label} {flushed_snapshot}")
        self._clear_streaming()

        # Display the ask_user question if stashed and not already
        # present in the streaming snapshot (avoids double-display).
        question = self._pending_ask_question
        self._pending_ask_question = ""
        if question and question not in flushed_snapshot:
            self._write_history(f"{label} {question}")

        self._waiting_for_input = True
        self._input_node_id = node_id or None
        self._input_graph_id = graph_id

        indicator = self.query_one("#processing-indicator", Label)
        indicator.update("Waiting for your input...")

        chat_input = self.query_one("#chat-input", ChatTextArea)
        chat_input.disabled = False
        node = self.runtime.graph.get_node(node_id) if node_id else None
        name = node.name if node else None
        chat_input.placeholder = (
            f"Type your response to {name}..." if name else "Type your response..."
        )
        chat_input.focus()

    def handle_node_completed(self, node_id: str) -> None:
        """Clear active node when it finishes."""
        if self._active_node_id == node_id:
            self._active_node_id = None

    def handle_internal_output(self, node_id: str, content: str) -> None:
        """Buffer output from non-client-facing nodes. Only display if logs are ON."""
        line = f"[dim cyan]⟨{node_id}⟩[/dim cyan] {content}"
        self._log_buffer.append(line)
        if self._show_logs:
            self._write_history(line)

    def handle_execution_paused(self, node_id: str, reason: str) -> None:
        """Show that execution has been paused."""
        msg = f"[bold yellow]⏸ Paused[/bold yellow] at [cyan]{node_id}[/cyan]"
        if reason:
            msg += f" [dim]({reason})[/dim]"
        self._write_history(msg)

    def handle_execution_resumed(self, node_id: str) -> None:
        """Show that execution has been resumed."""
        self._write_history(f"[bold green]▶ Resumed[/bold green] from [cyan]{node_id}[/cyan]")

    def handle_goal_achieved(self, data: dict[str, Any]) -> None:
        """Show goal achievement prominently."""
        self._write_history("[bold green]★ Goal achieved![/bold green]")

    def handle_constraint_violation(self, data: dict[str, Any]) -> None:
        """Show constraint violation as a warning."""
        desc = data.get("description", "Unknown constraint")
        self._write_history(f"[bold red]⚠ Constraint violation:[/bold red] {desc}")
