from __future__ import annotations

from framework.mcp.auth.auth_response_payloads import MCPAuthResponsePayloadFactory
from framework.mcp.auth.models import MCPAuthChallenge
from framework.mcp.integrations.generic import GenericMCPIntegrationAdapter
from framework.mcp.models import MCPServerConfig


def _config() -> MCPServerConfig:
    return MCPServerConfig(name="Github", transport="http", url="https://example.com/mcp")


def test_build_auth_required_payload():
    factory = MCPAuthResponsePayloadFactory()
    challenge = MCPAuthChallenge(
        auth_url="https://oauth.example.com/start",
        resource_metadata="https://api.example.com/.well-known/oauth-protected-resource",
        required_headers=["Authorization"],
        required_scopes=["repo"],
    )

    payload = factory.build_auth_required(_config(), challenge)

    assert payload["type"] == "auth_required"
    assert payload["server"] == "Github"
    assert payload["auth_url"] == "https://oauth.example.com/start"
    assert payload["required_scopes"] == ["repo"]


def test_build_auth_required_external_payload():
    factory = MCPAuthResponsePayloadFactory()
    challenge = MCPAuthChallenge(
        resource_metadata="https://api.example.com/.well-known/oauth-protected-resource"
    )

    payload = factory.build_auth_required_external(
        _config(),
        challenge,
        GenericMCPIntegrationAdapter(),
        credential_candidates=["Github", "github"],
    )

    assert payload["type"] == "auth_required_external"
    assert payload["action"] == "authorize_via_aden"
    assert payload["credential_candidates"] == ["Github", "github"]
