"""Base transport contract for MCP clients."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class MCPTransport(ABC):
    """Minimal sync transport interface used by MCP session runtime."""

    @abstractmethod
    def connect(self) -> None:
        """Establish transport connection."""

    @abstractmethod
    def list_tools(self) -> list[dict[str, Any]]:
        """List server tools in MCP schema format."""

    @abstractmethod
    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Invoke a tool and return MCP result content."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close transport connection."""

    def set_bearer_token(self, token: str) -> None:
        """Optional hook for HTTP transport token override."""
        _ = token

    def has_bearer_token(self) -> bool:
        """Optional hook indicating whether a token is currently set."""
        return False
