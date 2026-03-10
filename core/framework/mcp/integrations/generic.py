"""Generic standards-compliant integration adapter."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from framework.mcp.auth.models import MCPAuthChallenge
from framework.mcp.integrations.base import MCPIntegrationAdapter
from framework.mcp.models import MCPServerConfig


class GenericMCPIntegrationAdapter(MCPIntegrationAdapter):
    """Default adapter with provider-agnostic token lookup heuristics."""

    def credential_candidates(
        self, config: MCPServerConfig, challenge: MCPAuthChallenge
    ) -> list[str]:
        candidates: list[str] = []

        if config.oauth_credential_id:
            candidates.append(config.oauth_credential_id)

        candidates.append(config.name)
        slug = _slugify(config.name)
        if slug and slug != config.name:
            candidates.append(slug)
            candidates.append(f"mcp_{slug}")

        if config.url:
            host = urlparse(config.url).hostname
            if host:
                candidates.append(host)
                host_slug = _slugify(host)
                if host_slug:
                    candidates.append(host_slug)

        seen: set[str] = set()
        deduped: list[str] = []
        for item in candidates:
            if item and item not in seen:
                deduped.append(item)
                seen.add(item)
        return deduped

    def external_auth_message(self, config: MCPServerConfig, challenge: MCPAuthChallenge) -> str:
        return (
            f"Authorization required for MCP server '{config.name}'. "
            "No direct auth_url was provided and no reusable token was found. "
            "Authorize this integration in Aden and retry."
        )


def _slugify(value: str) -> str:
    value = value.strip().lower()
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")
