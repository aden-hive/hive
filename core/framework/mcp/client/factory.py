"""Factory helpers for MCP session runtime construction."""

from __future__ import annotations

from framework.mcp.auth import MCPAuthManager
from framework.mcp.models import MCPServerConfig
from framework.mcp.session import MCPClientSessionRuntime
from framework.mcp.transport import HttpMCPTransport, StdioMCPTransport


def create_session_runtime(config: MCPServerConfig) -> MCPClientSessionRuntime:
    """Create a runtime with correct transport/auth composition."""
    if config.transport == "stdio":
        transport = StdioMCPTransport(config)
        return MCPClientSessionRuntime(config=config, transport=transport, auth_manager=None)
    if config.transport == "http":
        transport = HttpMCPTransport(config)
        return MCPClientSessionRuntime(
            config=config,
            transport=transport,
            auth_manager=MCPAuthManager(),
        )
    raise ValueError(f"Unsupported transport: {config.transport}")
