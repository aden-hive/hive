from __future__ import annotations

from framework.mcp.auth.manager import MCPAuthManager
from framework.mcp.auth.models import MCPAuthToken
from framework.mcp.models import MCPServerConfig


class _Response:
    def __init__(self, headers=None, json_body=None, text=None):
        self.headers = headers or {}
        self._json_body = json_body
        self.text = text

    def json(self):
        if self._json_body is None:
            raise ValueError("no json")
        return self._json_body


class _TokenStore:
    def __init__(self, token: MCPAuthToken | None):
        self._token = token

    def resolve_token(self, credential_candidates: list[str]):
        _ = credential_candidates
        return self._token


def _config() -> MCPServerConfig:
    return MCPServerConfig(name="Github", transport="http", url="https://example.com/mcp")


def test_resolve_unauthorized_returns_auth_required_when_auth_url_exists():
    manager = MCPAuthManager(
        token_store=_TokenStore(
            MCPAuthToken(value="abc", credential_id="github", key_name="access_token")
        )
    )
    response = _Response(
        json_body={"auth_url": "https://github.com/login/oauth/authorize"},
    )

    decision = manager.resolve_unauthorized(_config(), response, token_already_tried=False)

    assert decision.kind == "auth_required"
    assert decision.payload["auth_url"] == "https://github.com/login/oauth/authorize"


def test_resolve_unauthorized_retries_with_existing_token_when_no_auth_url():
    manager = MCPAuthManager(
        token_store=_TokenStore(
            MCPAuthToken(value="abc", credential_id="github", key_name="access_token")
        )
    )
    response = _Response(
        headers={"WWW-Authenticate": 'Bearer realm="mcp", scope="repo"'},
    )

    decision = manager.resolve_unauthorized(_config(), response, token_already_tried=False)

    assert decision.kind == "retry_with_token"
    assert decision.token is not None
    assert decision.token.value == "abc"


def test_resolve_unauthorized_returns_external_auth_when_no_auth_url_and_no_token():
    manager = MCPAuthManager(token_store=_TokenStore(None))
    response = _Response(
        headers={"WWW-Authenticate": 'Bearer realm="mcp", resource_metadata="https://example.com/.well-known/oauth-protected-resource"'},
    )

    decision = manager.resolve_unauthorized(_config(), response, token_already_tried=False)

    assert decision.kind == "auth_required_external"
    assert decision.payload["action"] == "authorize_via_aden"
