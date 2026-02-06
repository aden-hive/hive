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

    def __init__(self, runtime: AgentRuntime):
        super().__init__()
        self.runtime = runtime
        self._current_exec_id: str | None = None
        self._streaming_snapshot: str = ""
        self._waiting_for_input: bool = False
        self._input_node_id: str | None = None

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

    def on_mount(self) -> None:
        """Add welcome message when widget mounts."""
        history = self.query_one("#chat-history", RichLog)
        history.write("[bold cyan]Chat REPL Ready[/bold cyan] — Type your input below\n")

    async def on_input_submitted(self, message: Input.Submitted) -> None:
        """Handle input submission — either start new execution or inject input."""
        user_input = message.value.strip()
        if not user_input:
            return

        # Client-facing input: route to the waiting node
        if self._waiting_for_input and self._input_node_id:
            self._write_history(f"[bold green]You:[/bold green] {user_input}")
            message.input.value = ""

            # Disable input while agent processes the response
            chat_input = self.query_one("#chat-input", Input)
            chat_input.disabled = True
            chat_input.placeholder = "Enter input for agent..."
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

            # Disable input while the agent is working
            chat_input = self.query_one("#chat-input", Input)
            chat_input.disabled = True

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
