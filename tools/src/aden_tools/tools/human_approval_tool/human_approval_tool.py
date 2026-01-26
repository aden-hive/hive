from typing import Any
from mcp.server.fastmcp import FastMCP

def register_tools(mcp: FastMCP) -> None:
    """Register human approval tools."""

    @mcp.tool()
    def ask_human_approval(question: str, context: str | None = None) -> str:
        """
        Ask a human for approval or input on a critical decision.
        
        When to use:
        - Before taking irreversible actions (deleting files, posting content)
        - When ambiguous situations require human judgment
        - When explicitly asked to check with the user
        
        Args:
            question: The specific question or approval request for the user
            context: Additional context to help the user decide (optional)
            
        Returns:
            Instructions for the agent to pause and wait.
        """
        # In the future, this tool could signal the runtime directly.
        # For now, it provides a standard way for the agent to request help.
        
        return (
            f"REQUESTING HUMAN APPROVAL\n"
            f"Question: {question}\n"
            f"Context: {context or 'None'}\n"
            f"\n"
            f"Please PAUSE execution now and wait for human input.\n"
            f"Resume when approval is granted."
        )
