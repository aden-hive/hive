"""Shared models for MCP client modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server connection."""

    name: str
    transport: Literal["stdio", "http"]

    # For STDIO transport
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None

    # For HTTP transport
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    rpc_paths: list[str] = field(default_factory=list)

    # Optional auth hints
    oauth_credential_id: str | None = None

    # Optional metadata
    description: str = ""


@dataclass
class MCPTool:
    """A tool available from an MCP server."""

    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str
