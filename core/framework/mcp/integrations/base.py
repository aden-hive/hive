"""Base contract for MCP integration adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod

from framework.mcp.auth.models import MCPAuthChallenge
from framework.mcp.models import MCPServerConfig


class MCPIntegrationAdapter(ABC):
    """Defines integration-specific auth behavior without touching transport."""

    @abstractmethod
    def credential_candidates(
        self, config: MCPServerConfig, challenge: MCPAuthChallenge
    ) -> list[str]:
        """Return credential IDs to probe for bearer token reuse."""

    @abstractmethod
    def external_auth_message(self, config: MCPServerConfig, challenge: MCPAuthChallenge) -> str:
        """Return user-facing message for external authorization requirement."""
