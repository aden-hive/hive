"""Registry for selecting integration adapters."""

from __future__ import annotations

from framework.mcp.auth.models import MCPAuthChallenge
from framework.mcp.integrations.base import MCPIntegrationAdapter
from framework.mcp.integrations.generic import GenericMCPIntegrationAdapter
from framework.mcp.models import MCPServerConfig


class MCPIntegrationRegistry:
    """Scope A registry: always resolves to generic adapter."""

    def __init__(self) -> None:
        self._generic = GenericMCPIntegrationAdapter()

    def resolve(
        self, config: MCPServerConfig, challenge: MCPAuthChallenge
    ) -> MCPIntegrationAdapter:
        _ = (config, challenge)
        return self._generic
