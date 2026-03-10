"""Typed errors for MCP client stack."""

from __future__ import annotations

from typing import Any


class MCPError(RuntimeError):
    """Base MCP client exception."""


class MCPTransportError(MCPError):
    """Raised for transport-level failures."""


class MCPHTTPUnauthorizedError(MCPTransportError):
    """Raised when an MCP HTTP call returns 401 Unauthorized."""

    def __init__(
        self,
        server_name: str,
        message: str,
        response: Any,
        rpc_path: str | None = None,
        attempted_auth: bool = False,
    ) -> None:
        super().__init__(message)
        self.server_name = server_name
        self.response = response
        self.rpc_path = rpc_path
        self.attempted_auth = attempted_auth


class MCPAuthRequiredError(MCPError):
    """Raised when user authorization is required and auth_url is available."""

    def __init__(self, server_name: str, payload: dict[str, Any]):
        message = payload.get("message") or f"OAuth authorization is required for '{server_name}'"
        super().__init__(message)
        self.server_name = server_name
        self.payload = payload


class MCPAuthRequiredExternalError(MCPError):
    """Raised when external pre-authorization is required (Scope B deferred)."""

    def __init__(self, server_name: str, payload: dict[str, Any]):
        message = payload.get("message") or (
            f"Authorization required for MCP server '{server_name}'. "
            "Please authorize from Aden and retry."
        )
        super().__init__(message)
        self.server_name = server_name
        self.payload = payload
