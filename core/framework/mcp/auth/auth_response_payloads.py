"""Payload builders for MCP auth-required responses."""

from __future__ import annotations

from typing import Any

from framework.mcp.auth.models import MCPAuthChallenge
from framework.mcp.integrations.base import MCPIntegrationAdapter
from framework.mcp.models import MCPServerConfig


class MCPAuthResponsePayloadFactory:
    """Builds auth-required payloads consumed by caller/UI layers."""

    def build_auth_required(
        self, config: MCPServerConfig, challenge: MCPAuthChallenge
    ) -> dict[str, Any]:
        return {
            "type": "auth_required",
            "server": config.name,
            "transport": config.transport,
            "auth_url": challenge.auth_url,
            "resource_metadata": challenge.resource_metadata,
            "required_headers": challenge.required_headers,
            "required_scopes": challenge.required_scopes,
            "message": f"OAuth authorization is required for '{config.name}'.",
        }

    def build_auth_required_external(
        self,
        config: MCPServerConfig,
        challenge: MCPAuthChallenge,
        adapter: MCPIntegrationAdapter,
        credential_candidates: list[str],
    ) -> dict[str, Any]:
        return {
            "type": "auth_required_external",
            "server": config.name,
            "transport": config.transport,
            "resource_metadata": challenge.resource_metadata,
            "required_headers": challenge.required_headers,
            "required_scopes": challenge.required_scopes,
            "credential_candidates": credential_candidates,
            "action": "authorize_via_aden",
            "message": adapter.external_auth_message(config, challenge),
        }
