"""Runtime orchestration for transport + auth manager."""

from __future__ import annotations

from typing import Any

from framework.mcp.auth.manager import MCPAuthManager
from framework.mcp.errors import (
    MCPAuthRequiredError,
    MCPAuthRequiredExternalError,
    MCPHTTPUnauthorizedError,
)
from framework.mcp.models import MCPServerConfig
from framework.mcp.session.retry import retry_once
from framework.mcp.transport.base import MCPTransport


class MCPClientSessionRuntime:
    """Coordinates MCP transport execution with Scope A auth behavior."""

    def __init__(
        self,
        config: MCPServerConfig,
        transport: MCPTransport,
        auth_manager: MCPAuthManager | None = None,
    ):
        self._config = config
        self._transport = transport
        self._auth_manager = auth_manager

    def connect(self) -> None:
        self._transport.connect()

    def disconnect(self) -> None:
        self._transport.disconnect()

    def list_tools(self) -> list[dict[str, Any]]:
        return self._run_with_auth(lambda: self._transport.list_tools())

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        return self._run_with_auth(lambda: self._transport.call_tool(tool_name, arguments))

    def _run_with_auth(self, operation):
        auth_manager = self._auth_manager
        if auth_manager is None:
            return operation()

        def should_retry(exc: Exception) -> bool:
            return isinstance(exc, MCPHTTPUnauthorizedError)

        first_unauthorized: MCPHTTPUnauthorizedError | None = None

        def op_with_capture():
            nonlocal first_unauthorized
            try:
                return operation()
            except MCPHTTPUnauthorizedError as exc:
                first_unauthorized = exc
                raise

        def prepare_retry() -> None:
            if first_unauthorized is None:
                return
            decision = auth_manager.resolve_unauthorized(
                self._config,
                first_unauthorized.response,
                token_already_tried=first_unauthorized.attempted_auth
                or self._transport.has_bearer_token(),
            )
            if decision.kind == "retry_with_token" and decision.token is not None:
                self._transport.set_bearer_token(decision.token.value)
                return
            if decision.kind == "auth_required":
                raise MCPAuthRequiredError(self._config.name, decision.payload)
            raise MCPAuthRequiredExternalError(self._config.name, decision.payload)

        try:
            return retry_once(
                operation=op_with_capture,
                should_retry=should_retry,
                before_retry=prepare_retry,
            )
        except MCPHTTPUnauthorizedError as retry_exc:
            # Retry was attempted and still unauthorized.
            decision = auth_manager.resolve_unauthorized(
                self._config,
                retry_exc.response,
                token_already_tried=True,
            )
            if decision.kind == "auth_required":
                raise MCPAuthRequiredError(self._config.name, decision.payload) from retry_exc
            raise MCPAuthRequiredExternalError(self._config.name, decision.payload) from retry_exc
