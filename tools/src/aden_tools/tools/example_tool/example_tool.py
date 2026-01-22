"""
Example Tool - A simple text processing tool for FastMCP.

Demonstrates native FastMCP tool registration pattern.
"""
from __future__ import annotations

from fastmcp import FastMCP


def register_tools(mcp: FastMCP) -> None:
    """Register example tools with the MCP server."""

    @mcp.tool()
    def example_tool(
        message: str,
        uppercase: bool = False,
        repeat: int = 1,
    ) -> str:
        """
        A simple example tool that processes text messages.
        Use this tool when you need to transform or repeat text.

        Args:
            message: The message to process (1-1000 chars)
            uppercase: If True, convert the message to uppercase
            repeat: Number of times to repeat the message (1-10)

        Returns:
            The processed message string
        """
        try:
            # Validate inputs
            if not message or len(message) > 1000:
                return "Error: message must be 1-1000 characters"
            if repeat < 1 or repeat > 10:
                return "Error: repeat must be 1-10"

            # Process the message
            result = message
            if uppercase:
                result = result.upper()

            # Repeat if requested
            if repeat > 1:
                result = " ".join([result] * repeat)

            return result

        except Exception as e:
            return f"Error processing message: {str(e)}"
