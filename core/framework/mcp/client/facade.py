"""Stable MCP client facade used by runner/tool registry."""

from __future__ import annotations

import logging
from typing import Any

from framework.mcp.client.factory import create_session_runtime
from framework.mcp.models import MCPServerConfig, MCPTool

logger = logging.getLogger(__name__)


class MCPClient:
    """Synchronous MCP client facade preserving existing runner interface."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._runtime = create_session_runtime(config)
        self._tools: dict[str, MCPTool] = {}
        self._connected = False

    def connect(self) -> None:
        if self._connected:
            return
        self._runtime.connect()
        self._discover_tools()
        self._connected = True

    def _discover_tools(self) -> None:
        tools_list = self._runtime.list_tools()
        self._tools = {}
        for tool_data in tools_list:
            tool = MCPTool(
                name=tool_data["name"],
                description=tool_data.get("description", ""),
                input_schema=tool_data.get("inputSchema", {}),
                server_name=self.config.name,
            )
            self._tools[tool.name] = tool
        logger.info(
            "Discovered %s tools from '%s': %s",
            len(self._tools),
            self.config.name,
            list(self._tools.keys()),
        )

    def list_tools(self) -> list[MCPTool]:
        if not self._connected:
            self.connect()
        return list(self._tools.values())

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        if not self._connected:
            self.connect()
        if tool_name not in self._tools:
            raise ValueError(f"Unknown tool: {tool_name}")
        return self._runtime.call_tool(tool_name, arguments)

    def disconnect(self) -> None:
        self._runtime.disconnect()
        self._connected = False
        logger.info("Disconnected from MCP server '%s'", self.config.name)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
