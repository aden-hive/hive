from __future__ import annotations

from framework.mcp.auth.models import MCPAuthChallenge, MCPAuthToken
from framework.mcp.auth.strategy import ScopeAAuthStrategy


def test_auth_url_has_priority_over_token_reuse():
    strategy = ScopeAAuthStrategy()
    challenge = MCPAuthChallenge(auth_url="https://oauth.example.com/start")
    token = MCPAuthToken(value="abc", credential_id="github", key_name="access_token")

    decision = strategy.decide(
        challenge=challenge,
        token=token,
        token_already_tried=False,
        auth_required_payload={"type": "auth_required"},
        auth_required_external_payload={"type": "auth_required_external"},
    )

    assert decision.kind == "auth_required"


def test_retry_with_token_when_available_and_not_tried():
    strategy = ScopeAAuthStrategy()
    challenge = MCPAuthChallenge(auth_url=None)
    token = MCPAuthToken(value="abc", credential_id="github", key_name="access_token")

    decision = strategy.decide(
        challenge=challenge,
        token=token,
        token_already_tried=False,
        auth_required_payload={"type": "auth_required"},
        auth_required_external_payload={"type": "auth_required_external"},
    )

    assert decision.kind == "retry_with_token"
    assert decision.token is token


def test_auth_required_external_when_no_token():
    strategy = ScopeAAuthStrategy()
    challenge = MCPAuthChallenge(auth_url=None)

    decision = strategy.decide(
        challenge=challenge,
        token=None,
        token_already_tried=False,
        auth_required_payload={"type": "auth_required"},
        auth_required_external_payload={"type": "auth_required_external"},
    )

    assert decision.kind == "auth_required_external"
