from __future__ import annotations

from framework.mcp.auth.http_challenge_parser import MCPHTTPAuthChallengeParser


class _Response:
    def __init__(self, headers=None, json_body=None, text=None):
        self.headers = headers or {}
        self._json_body = json_body
        self.text = text

    def json(self):
        if self._json_body is None:
            raise ValueError("no json")
        return self._json_body


def test_parse_www_authenticate_header_fields():
    parser = MCPHTTPAuthChallengeParser()
    response = _Response(
        headers={
            "WWW-Authenticate": (
                'Bearer realm="mcp", '
                'auth_url="https://auth.example.com/authorize", '
                'resource_metadata="https://api.example.com/.well-known/resource", '
                'scope="repo read:user"'
            )
        }
    )

    challenge = parser.parse(response)

    assert challenge.auth_url == "https://auth.example.com/authorize"
    assert challenge.resource_metadata == "https://api.example.com/.well-known/resource"
    assert challenge.required_scopes == ["repo", "read:user"]


def test_parse_body_auth_url_fallback():
    parser = MCPHTTPAuthChallengeParser()
    response = _Response(
        json_body={
            "error": {"auth_url": "https://oauth.example.com/start"},
            "required_headers": ["Authorization"],
            "required_scopes": ["read", "write"],
        }
    )

    challenge = parser.parse(response)

    assert challenge.auth_url == "https://oauth.example.com/start"
    assert challenge.required_headers == ["Authorization"]
    assert challenge.required_scopes == ["read", "write"]


def test_parse_location_fallback_when_no_auth_url_present():
    parser = MCPHTTPAuthChallengeParser()
    response = _Response(headers={"Location": "https://oauth.example.com/location"})

    challenge = parser.parse(response)

    assert challenge.auth_url == "https://oauth.example.com/location"
