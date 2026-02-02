"""
Chat / REPL Widget - Uses TextArea for reliable display.
"""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, TextArea

from framework.runtime.agent_runtime import AgentRuntime


class ChatRepl(Vertical):
    """Widget for interactive chat/REPL."""

    DEFAULT_CSS = """
    ChatRepl {
        width: 100%;
        height: 100%;
        layout: vertical;
    }

    ChatRepl > TextArea {
        width: 100%;
        height: 1fr;
        background: $surface;
        border: none;
        scrollbar-background: $panel;
        scrollbar-color: $primary;
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

    def compose(self) -> ComposeResult:
        # Use TextArea (read-only) like LogPane
        yield TextArea("", id="chat-history", read_only=True)
        yield Input(placeholder="Enter input for agent...", id="chat-input")

    def on_mount(self) -> None:
        """Add welcome message when widget mounts."""
        history = self.query_one("#chat-history", TextArea)
        history.load_text("Chat REPL Ready - Type your input below\n")
        with open("tui_debug.log", "a") as f:
            f.write("DEBUG: ChatREPL mounted with welcome message\n")

    async def on_input_submitted(self, message: Input.Submitted) -> None:
        """Handle input submission."""
        with open("tui_debug.log", "a") as f:
            f.write("DEBUG: on_input_submitted called\n")

        user_input = message.value.strip()

        with open("tui_debug.log", "a") as f:
            f.write(f"DEBUG: ChatREPL input: '{user_input}'\n")

        if not user_input:
            return

        # Get chat history
        with open("tui_debug.log", "a") as f:
            f.write("DEBUG: Getting chat history\n")
        history = self.query_one("#chat-history", TextArea)

        # Display user message
        with open("tui_debug.log", "a") as f:
            f.write("DEBUG: Adding user message\n")
        current_text = history.text
        history.load_text(f"{current_text}\nYou: {user_input}\n")

        with open("tui_debug.log", "a") as f:
            f.write("DEBUG: User message added\n")

        # Clear input
        message.input.value = ""

        # Execute agent
        try:
            with open("tui_debug.log", "a") as f:
                f.write("DEBUG: Starting agent execution\n")

            # Show processing
            current_text = history.text
            history.load_text(f"{current_text}Agent is processing...\n")

            with open("tui_debug.log", "a") as f:
                f.write("DEBUG: Processing message shown\n")

            # Get entry point
            entry_points = self.runtime.get_entry_points()
            if not entry_points:
                current_text = history.text
                history.load_text(f"{current_text}Error: No entry points\n")
                return

            with open("tui_debug.log", "a") as f:
                f.write("DEBUG: Calling trigger_and_wait\n")

            # Execute
            result = await self.runtime.trigger_and_wait(
                entry_point_id=entry_points[0].id,
                input_data={"input_string": user_input},
                timeout=30.0,
            )

            with open("tui_debug.log", "a") as f:
                f.write(f"DEBUG: Got result: {result}\n")

            # Remove "processing" line and display result
            lines = history.text.split("\n")
            lines = [line for line in lines if "processing" not in line.lower()]

            # Display result
            if result and result.success and result.output:
                output_str = str(result.output.get("output_string", result.output))
                lines.append(f"Agent: {output_str}")
                with open("tui_debug.log", "a") as f:
                    f.write("DEBUG: Added success result\n")
            elif result and result.error:
                lines.append(f"Error: {result.error}")
            else:
                lines.append("No result")

            history.load_text("\n".join(lines) + "\n")

            with open("tui_debug.log", "a") as f:
                f.write("DEBUG: Execution complete\n")

        except Exception as e:
            with open("tui_debug.log", "a") as f:
                f.write(f"ERROR: Exception in handler: {e}\n")
                import traceback

                f.write(f"{traceback.format_exc()}\n")
            current_text = history.text
            lines = current_text.split("\n")
            lines = [line for line in lines if "processing" not in line.lower()]
            lines.append(f"Error: {str(e)}")
            history.load_text("\n".join(lines) + "\n")
