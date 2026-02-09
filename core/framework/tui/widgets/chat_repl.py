"""
Chat / REPL Widget - Uses RichLog for append-only, selection-safe display.

Streaming display approach:
- The processing-indicator Label is used as a live status bar during streaming
  (Label.update() replaces text in-place, unlike RichLog which is append-only).
- On EXECUTION_COMPLETED, the final output is written to RichLog as permanent history.
- Tool events are written directly to RichLog as discrete status lines.

Client-facing input:
- When a client_facing=True EventLoopNode emits CLIENT_INPUT_REQUESTED, the
  ChatRepl transitions to "waiting for input" state: input is re-enabled and
  subsequent submissions are routed to runtime.inject_input() instead of
  starting a new execution.
"""

import asyncio
import re
import threading
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label

from framework.runtime.agent_runtime import AgentRuntime
from framework.tui.widgets.selectable_rich_log import SelectableRichLog as RichLog


class ChatRepl(Vertical):
    """Widget for interactive chat/REPL."""

    DEFAULT_CSS = """
    ChatRepl {
        width: 100%;
        height: 100%;
        layout: vertical;
    }

    ChatRepl > RichLog {
        width: 100%;
        height: 1fr;
        background: $surface;
        border: none;
        scrollbar-background: $panel;
        scrollbar-color: $primary;
    }

    ChatRepl > #processing-indicator {
        width: 100%;
        height: 1;
        background: $primary 20%;
        color: $text;
        text-style: bold;
        display: none;
    }

    ChatRepl > Input {
        width: 100%;
        height: auto;
        dock: bottom;
        background: $surface;
        border: tall $primary;
        margin-top: 1;
    }

    ChatRepl > Input:focus {
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
        self._waiting_for_input: bool = False
        self._input_node_id: str | None = None
        self._resume_session = resume_session
        self._resume_checkpoint = resume_checkpoint

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
        yield Label("Agent is processing...", id="processing-indicator")
        yield Input(placeholder="Enter input for agent...", id="chat-input")

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
        """Write to chat history, only auto-scrolling if user is at the bottom."""
        history = self.query_one("#chat-history", RichLog)
        was_at_bottom = history.is_vertical_scroll_end
        history.write(self._linkify(content))
        if was_at_bottom:
            history.scroll_end(animate=False)

    async def _handle_command(self, command: str) -> None:
        """Handle slash commands for session and checkpoint operations."""
        parts = command.split(maxsplit=2)
        cmd = parts[0].lower()

        if cmd == "/help":
            self._write_history("""[bold cyan]Available Commands:[/bold cyan]
  [bold]/sessions[/bold]                    - List all sessions for this agent
  [bold]/sessions[/bold] <session_id>       - Show session details and checkpoints
  [bold]/resume[/bold]                     - Resume latest paused/failed session
  [bold]/resume[/bold] <session_id>         - Resume session from where it stopped
  [bold]/recover[/bold] <session_id> <cp_id> - Recover from specific checkpoint
  [bold]/pause[/bold]                      - Pause current execution (Ctrl+Z)
  [bold]/help[/bold]                       - Show this help message

[dim]Examples:[/dim]
  /sessions                              [dim]# List all sessions[/dim]
  /sessions session_20260208_143022      [dim]# Show session details[/dim]
  /resume                                [dim]# Resume latest session (from state)[/dim]
  /resume session_20260208_143022        [dim]# Resume specific session (from state)[/dim]
  /recover session_20260208_143022 cp_xxx [dim]# Recover from specific checkpoint[/dim]
  /pause                                 [dim]# Pause (or Ctrl+Z)[/dim]
""")
        elif cmd == "/sessions":
            session_id = parts[1].strip() if len(parts) > 1 else None
            await self._cmd_sessions(session_id)
        elif cmd == "/resume":
            # Resume from session state (not checkpoint-based)
            if len(parts) < 2:
                session_id = await self._find_latest_resumable_session()
                if not session_id:
                    self._write_history("[bold red]No resumable sessions found[/bold red]")
                    self._write_history("  Tip: Use [bold]/sessions[/bold] to see all sessions")
                    return
            else:
                session_id = parts[1].strip()
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
        elif cmd == "/pause":
            await self._cmd_pause()
        else:
            self._write_history(
                f"[bold red]Unknown command:[/bold red] {cmd}\n"
                "Type [bold]/help[/bold] for available commands"
            )

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

        for session_dir in session_dirs[:10]:  # Show last 10 sessions
            session_id = session_dir.name
            state_file = session_dir / "state.json"

            if not state_file.exists():
                continue

            # Read session state
            try:
                import json

                with open(state_file) as f:
                    state = json.load(f)

                status = state.get("status", "unknown").upper()

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

                # Check for checkpoints
                checkpoint_dir = session_dir / "checkpoints"
                checkpoint_count = 0
                if checkpoint_dir.exists():
                    checkpoint_files = list(checkpoint_dir.glob("cp_*.json"))
                    checkpoint_count = len(checkpoint_files)

                # Session line
                self._write_history(f"📋 [bold]{session_id}[/bold]")
                self._write_history(f"   Status: {status_colored}  Checkpoints: {checkpoint_count}")

                if checkpoint_count > 0:
                    self._write_history(f"   [dim]Resume: /resume {session_id}[/dim]")

                self._write_history("")  # Blank line

            except Exception as e:
                self._write_history(f"   [dim red]Error reading: {e}[/dim red]")

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
                    "paused_at": paused_at,
                    "memory": state.get("memory", {}),
                    "execution_path": progress.get("path", []),
                    "node_visit_counts": progress.get("node_visit_counts", {}),
                }
                resume_info = f"From node: [cyan]{paused_at}[/cyan]"
            else:
                # No paused_at - just retry with same input
                resume_session_state = {}
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
            chat_input = self.query_one("#chat-input", Input)
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
                "resume_from_checkpoint": checkpoint_id,
            }

            # Show indicator
            indicator = self.query_one("#processing-indicator", Label)
            indicator.update("Recovering from checkpoint...")
            indicator.display = True

            # Update placeholder
            chat_input = self.query_one("#chat-input", Input)
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
                            }
                        )
                except Exception:
                    continue

            if resumable:
                self._write_history("\n[bold yellow]⚠ Non-terminated sessions found:[/bold yellow]")
                for i, session in enumerate(resumable[:3], 1):  # Show top 3
                    status = session["status"]
                    session_id = session["session_id"]

                    # Color code status
                    if status == "PAUSED":
                        status_colored = f"[yellow]{status}[/yellow]"
                    elif status == "FAILED":
                        status_colored = f"[red]{status}[/red]"
                    elif status == "CANCELLED":
                        status_colored = f"[dim yellow]{status}[/dim yellow]"
                    else:
                        status_colored = f"[dim]{status}[/dim]"

                    self._write_history(f"  {i}. {session_id[:32]}... [{status_colored}]")

                self._write_history("\n[bold cyan]What would you like to do?[/bold cyan]")
                self._write_history("  • Type [bold]/resume[/bold] to continue the latest session")
                self._write_history(
                    f"  • Type [bold]/resume {resumable[0]['session_id']}[/bold] "
                    "for specific session"
                )
                self._write_history("  • Or just type your input to start a new session\n")

        except Exception:
            # Silently fail - don't block TUI startup
            pass

    async def on_input_submitted(self, message: Input.Submitted) -> None:
        """Handle input submission — either start new execution or inject input."""
        user_input = message.value.strip()
        if not user_input:
            return

        # Handle commands (starting with /) - ALWAYS process commands first
        # Commands work during execution, during client-facing input, anytime
        if user_input.startswith("/"):
            await self._handle_command(user_input)
            message.input.value = ""
            return

        # Client-facing input: route to the waiting node
        if self._waiting_for_input and self._input_node_id:
            self._write_history(f"[bold green]You:[/bold green] {user_input}")
            message.input.value = ""

            # Keep input enabled for commands (but change placeholder)
            chat_input = self.query_one("#chat-input", Input)
            chat_input.placeholder = "Commands: /pause, /sessions (agent processing...)"
            self._waiting_for_input = False

            indicator = self.query_one("#processing-indicator", Label)
            indicator.update("Thinking...")

            node_id = self._input_node_id
            self._input_node_id = None

            try:
                future = asyncio.run_coroutine_threadsafe(
                    self.runtime.inject_input(node_id, user_input),
                    self._agent_loop,
                )
                await asyncio.wrap_future(future)
            except Exception as e:
                self._write_history(f"[bold red]Error delivering input:[/bold red] {e}")
            return

        # Double-submit guard: reject input while an execution is in-flight
        if self._current_exec_id is not None:
            self._write_history("[dim]Agent is still running — please wait.[/dim]")
            return

        indicator = self.query_one("#processing-indicator", Label)

        # Append user message and clear input
        self._write_history(f"[bold green]You:[/bold green] {user_input}")
        message.input.value = ""

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
            self._streaming_snapshot = ""

            # Show processing indicator
            indicator.update("Thinking...")
            indicator.display = True

            # Keep input enabled for commands during execution
            chat_input = self.query_one("#chat-input", Input)
            chat_input.placeholder = "Commands available: /pause, /sessions, /help"

            # Submit execution to the dedicated agent loop so blocking
            # runtime code (LLM, MCP tools) never touches Textual's loop.
            # trigger() returns immediately with an exec_id; the heavy
            # execution task runs entirely on the agent thread.
            future = asyncio.run_coroutine_threadsafe(
                self.runtime.trigger(
                    entry_point_id=entry_point.id,
                    input_data={input_key: user_input},
                ),
                self._agent_loop,
            )
            # wrap_future lets us await without blocking Textual's loop
            self._current_exec_id = await asyncio.wrap_future(future)

        except Exception as e:
            indicator.display = False
            self._current_exec_id = None
            # Re-enable input on error
            chat_input = self.query_one("#chat-input", Input)
            chat_input.disabled = False
            self._write_history(f"[bold red]Error:[/bold red] {e}")

    # -- Event handlers called by app.py _handle_event --

    def handle_text_delta(self, content: str, snapshot: str) -> None:
        """Handle a streaming text token from the LLM."""
        self._streaming_snapshot = snapshot

        # Show a truncated live preview in the indicator label
        indicator = self.query_one("#processing-indicator", Label)
        preview = snapshot[-80:] if len(snapshot) > 80 else snapshot
        # Replace newlines for single-line display
        preview = preview.replace("\n", " ")
        indicator.update(
            f"Thinking: ...{preview}" if len(snapshot) > 80 else f"Thinking: {preview}"
        )

    def handle_tool_started(self, tool_name: str, tool_input: dict[str, Any]) -> None:
        """Handle a tool call starting."""
        # Update indicator to show tool activity
        indicator = self.query_one("#processing-indicator", Label)
        indicator.update(f"Using tool: {tool_name}...")

        # Write a discrete status line to history
        self._write_history(f"[dim]Tool: {tool_name}[/dim]")

    def handle_tool_completed(self, tool_name: str, result: str, is_error: bool) -> None:
        """Handle a tool call completing."""
        result_str = str(result)
        preview = result_str[:200] + "..." if len(result_str) > 200 else result_str
        preview = preview.replace("\n", " ")

        if is_error:
            self._write_history(f"[dim red]Tool {tool_name} error: {preview}[/dim red]")
        else:
            self._write_history(f"[dim]Tool {tool_name} result: {preview}[/dim]")

        # Restore thinking indicator
        indicator = self.query_one("#processing-indicator", Label)
        indicator.update("Thinking...")

    def handle_execution_completed(self, output: dict[str, Any]) -> None:
        """Handle execution finishing successfully."""
        indicator = self.query_one("#processing-indicator", Label)
        indicator.display = False

        # Write the final streaming snapshot to permanent history (if any)
        if self._streaming_snapshot:
            self._write_history(f"[bold blue]Agent:[/bold blue] {self._streaming_snapshot}")
        else:
            output_str = str(output.get("output_string", output))
            self._write_history(f"[bold blue]Agent:[/bold blue] {output_str}")
        self._write_history("")  # separator

        self._current_exec_id = None
        self._streaming_snapshot = ""
        self._waiting_for_input = False
        self._input_node_id = None

        # Re-enable input
        chat_input = self.query_one("#chat-input", Input)
        chat_input.disabled = False
        chat_input.placeholder = "Enter input for agent..."
        chat_input.focus()

    def handle_execution_failed(self, error: str) -> None:
        """Handle execution failing."""
        indicator = self.query_one("#processing-indicator", Label)
        indicator.display = False

        self._write_history(f"[bold red]Error:[/bold red] {error}")
        self._write_history("")  # separator

        self._current_exec_id = None
        self._streaming_snapshot = ""
        self._waiting_for_input = False
        self._input_node_id = None

        # Re-enable input
        chat_input = self.query_one("#chat-input", Input)
        chat_input.disabled = False
        chat_input.placeholder = "Enter input for agent..."
        chat_input.focus()

    def handle_input_requested(self, node_id: str) -> None:
        """Handle a client-facing node requesting user input.

        Transitions to 'waiting for input' state: flushes the current
        streaming snapshot to history, re-enables the input widget,
        and sets a flag so the next submission routes to inject_input().
        """
        # Flush accumulated streaming text as agent output
        if self._streaming_snapshot:
            self._write_history(f"[bold blue]Agent:[/bold blue] {self._streaming_snapshot}")
            self._streaming_snapshot = ""

        self._waiting_for_input = True
        self._input_node_id = node_id or None

        indicator = self.query_one("#processing-indicator", Label)
        indicator.update("Waiting for your input...")

        chat_input = self.query_one("#chat-input", Input)
        chat_input.disabled = False
        chat_input.placeholder = "Type your response..."
        chat_input.focus()
