"""
Chat / REPL Widget.
"""

from textual.widgets import Input, ListView, ListItem, Static
from textual.containers import Vertical
from textual.app import ComposeResult
from framework.runtime.agent_runtime import AgentRuntime

class ChatRepl(Vertical):
    """Widget for interactive chat/REPL."""

    def __init__(self, runtime: AgentRuntime):
        super().__init__()
        self.runtime = runtime

    def compose(self) -> ComposeResult:
        yield ListView(id="chat-history")
        yield Input(placeholder="Enter command or chat...", id="chat-input")

    async def on_input_submitted(self, message: Input.Submitted) -> None:
        """Handle input submission."""
        user_input = message.value
        if not user_input:
            return
        
        # Display user message
        list_view = self.query_one("#chat-history", ListView)
        list_view.append(ListItem(Static(f"> {user_input}")))
        
        # Clear input
        message.input.value = ""
        
        # Process input (placeholder)
        # await self.runtime.process_input(user_input)
