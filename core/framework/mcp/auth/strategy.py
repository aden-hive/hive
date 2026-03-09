"""Scope A auth decision strategy."""

from __future__ import annotations

from framework.mcp.auth.models import MCPAuthChallenge, MCPAuthDecision, MCPAuthToken


class ScopeAAuthStrategy:
    """Applies Scope A source-of-truth decision order."""

    def decide(
        self,
        challenge: MCPAuthChallenge,
        token: MCPAuthToken | None,
        token_already_tried: bool,
        auth_required_payload: dict,
        auth_required_external_payload: dict,
    ) -> MCPAuthDecision:
        if challenge.auth_url:
            return MCPAuthDecision(kind="auth_required", payload=auth_required_payload)

        if token is not None and not token_already_tried:
            return MCPAuthDecision(kind="retry_with_token", token=token)

        return MCPAuthDecision(
            kind="auth_required_external",
            payload=auth_required_external_payload,
        )
