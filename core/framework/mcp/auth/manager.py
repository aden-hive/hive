"""Auth manager for MCP HTTP 401 handling (Scope A behavior)."""

from __future__ import annotations

from typing import Any

from framework.mcp.auth.challenge_parser import MCPAuthChallengeParser
from framework.mcp.auth.models import MCPAuthChallenge, MCPAuthDecision
from framework.mcp.auth.payload_builder import MCPAuthPayloadBuilder
from framework.mcp.auth.strategy import ScopeAAuthStrategy
from framework.mcp.auth.token_store import MCPTokenStore
from framework.mcp.integrations.registry import MCPIntegrationRegistry
from framework.mcp.models import MCPServerConfig


class MCPAuthManager:
    """Thin orchestrator for challenge parsing, token lookup, and auth decisions."""

    def __init__(
        self,
        token_store: MCPTokenStore | None = None,
        integration_registry: MCPIntegrationRegistry | None = None,
        strategy: ScopeAAuthStrategy | None = None,
        challenge_parser: MCPAuthChallengeParser | None = None,
        payload_builder: MCPAuthPayloadBuilder | None = None,
    ):
        self._token_store = token_store or MCPTokenStore()
        self._integration_registry = integration_registry or MCPIntegrationRegistry()
        self._strategy = strategy or ScopeAAuthStrategy()
        self._challenge_parser = challenge_parser or MCPAuthChallengeParser()
        self._payload_builder = payload_builder or MCPAuthPayloadBuilder()

    def resolve_unauthorized(
        self,
        config: MCPServerConfig,
        response: Any,
        token_already_tried: bool,
    ) -> MCPAuthDecision:
        challenge = self._challenge_parser.parse(response)
        adapter = self._integration_registry.resolve(config, challenge)
        candidates = adapter.credential_candidates(config, challenge)
        token = None
        if not challenge.auth_url and not token_already_tried:
            token = self._token_store.resolve_token(candidates)

        return self._strategy.decide(
            challenge=challenge,
            token=token,
            token_already_tried=token_already_tried,
            auth_required_payload=self._payload_builder.build_auth_required(config, challenge),
            auth_required_external_payload=self._payload_builder.build_auth_required_external(
                config,
                challenge,
                adapter,
                candidates,
            ),
        )

    # Compatibility shims to avoid breaking internal call sites while logic is modularized.
    def _parse_challenge(self, response: Any) -> MCPAuthChallenge:
        return self._challenge_parser.parse(response)

    def _build_auth_required_payload(
        self, config: MCPServerConfig, challenge: MCPAuthChallenge
    ) -> dict[str, Any]:
        return self._payload_builder.build_auth_required(config, challenge)

    def _build_auth_required_external_payload(
        self,
        config: MCPServerConfig,
        challenge: MCPAuthChallenge,
        credential_candidates: list[str],
    ) -> dict[str, Any]:
        adapter = self._integration_registry.resolve(config, challenge)
        return self._payload_builder.build_auth_required_external(
            config, challenge, adapter, credential_candidates
        )
