"""HTTP MCP transport with JSON-RPC invocation."""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlsplit

import httpx

from framework.mcp.errors import MCPHTTPUnauthorizedError, MCPTransportError
from framework.mcp.models import MCPServerConfig
from framework.mcp.transport.base import MCPTransport

logger = logging.getLogger(__name__)


class HttpMCPTransport(MCPTransport):
    """HTTP transport for MCP servers."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._http_client: httpx.Client | None = None
        self._origin: str | None = None
        self._base_path: str = ""
        self._rpc_paths: list[str] = []
        self._bearer_token: str | None = None

    def connect(self) -> None:
        if not self.config.url:
            raise ValueError("url is required for HTTP transport")

        split = urlsplit(self.config.url)
        if not split.scheme or not split.netloc:
            raise ValueError(f"Invalid MCP HTTP URL: {self.config.url}")

        self._origin = f"{split.scheme}://{split.netloc}"
        self._base_path = split.path.rstrip("/")
        self._rpc_paths = self._build_rpc_paths()
        self._http_client = httpx.Client(
            base_url=self._origin,
            headers=self.config.headers,
            timeout=30.0,
        )

        health_path = f"{self._base_path}/health" if self._base_path else "/health"
        try:
            response = self._http_client.get(health_path)
            if response.status_code == 401:
                logger.info(
                    "Health check for MCP server '%s' returned 401 (authorization may be required)",
                    self.config.name,
                )
            else:
                response.raise_for_status()
                logger.info(
                    "Connected to MCP server '%s' via HTTP at %s",
                    self.config.name,
                    self.config.url,
                )
        except Exception as e:
            logger.warning("Health check failed for MCP server '%s': %s", self.config.name, e)

    def _build_rpc_paths(self) -> list[str]:
        candidates: list[str] = []
        if self.config.rpc_paths:
            candidates.extend(self.config.rpc_paths)
        elif self._base_path:
            candidates.append(self._base_path)
        else:
            candidates.extend(["/mcp/v1", "/mcp"])

        normalized: list[str] = []
        seen: set[str] = set()
        for path in candidates:
            if not path:
                continue
            norm = path if path.startswith("/") else f"/{path}"
            if norm not in seen:
                normalized.append(norm)
                seen.add(norm)
        return normalized

    def _request_headers(self) -> dict[str, str] | None:
        if not self._bearer_token:
            return None
        return {"Authorization": f"Bearer {self._bearer_token}"}

    def _rpc(self, method: str, params: dict[str, Any], request_id: int) -> dict[str, Any]:
        if not self._http_client:
            raise MCPTransportError("HTTP client not initialized")

        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        headers = self._request_headers()

        errors: list[str] = []
        unauthorized_response = None
        unauthorized_path = None
        attempted_auth = self.has_bearer_token() or bool(
            self._http_client.headers.get("Authorization")
        )

        for path in self._rpc_paths:
            try:
                response = self._http_client.post(path, json=payload, headers=headers)
            except Exception as e:
                errors.append(f"{path} -> {e}")
                continue
            if response.status_code == 401:
                unauthorized_response = response
                unauthorized_path = path
                break
            if response.status_code in (404, 405, 406):
                errors.append(f"{path} -> {response.status_code}")
                continue

            try:
                response.raise_for_status()
            except Exception as e:
                errors.append(f"{path} -> {e}")
                continue

            try:
                data = response.json()
            except json.JSONDecodeError as e:
                raise MCPTransportError(
                    f"Failed to parse MCP response from {path}: {e}"
                ) from e

            if "error" in data:
                raise MCPTransportError(f"MCP error: {data['error']}")
            return data

        if unauthorized_response is not None:
            raise MCPHTTPUnauthorizedError(
                server_name=self.config.name,
                message=(
                    f"MCP server '{self.config.name}' returned 401 Unauthorized "
                    f"for RPC path {unauthorized_path}"
                ),
                response=unauthorized_response,
                rpc_path=unauthorized_path,
                attempted_auth=attempted_auth,
            )

        detail = ", ".join(errors) if errors else "no eligible RPC path response"
        raise MCPTransportError(
            f"Failed to call MCP RPC '{method}' via HTTP ({self.config.name}): {detail}"
        )

    def list_tools(self) -> list[dict[str, Any]]:
        data = self._rpc("tools/list", {}, request_id=1)
        return data.get("result", {}).get("tools", [])

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        data = self._rpc(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
            request_id=2,
        )
        return data.get("result", {}).get("content", [])

    def disconnect(self) -> None:
        if self._http_client:
            self._http_client.close()
            self._http_client = None

    def set_bearer_token(self, token: str) -> None:
        self._bearer_token = token

    def has_bearer_token(self) -> bool:
        return bool(self._bearer_token)
