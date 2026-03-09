"""Compatibility shim for legacy MCP client imports.

Use ``framework.mcp.client`` and ``framework.mcp.models`` directly for new code.
"""

from framework.mcp.client import MCPClient
from framework.mcp.models import MCPServerConfig, MCPTool

__all__ = ["MCPClient", "MCPServerConfig", "MCPTool"]
