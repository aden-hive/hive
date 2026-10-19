"""Smoke tests for the Mattermost tool.

Mock-based tests — see the docstring on test_discord_tool.py for why
this suite is intentionally thin. Mattermost differs from Discord in
one important way: it needs *two* credentials (token + URL), so we
defend both missing-credential paths separately.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aden_tools.tools.mattermost_tool.mattermost_tool import (
    MAX_MESSAGE_LENGTH,
    MAX_RETRIES,
    register_tools,
)

_TOKEN = "test-access-token"
_URL = "https://mattermost.example.com"


def _register(credentials=None):
    """Register Mattermost tools onto a stub MCP. Returns a name→fn lookup."""
    mcp = MagicMock()
    fns: dict[str, callable] = {}
    mcp.tool.return_value = lambda fn: fns.setdefault(fn.__name__, fn) or fn
    register_tools(mcp, credentials=credentials)
    return fns


def _creds(token=_TOKEN, url=_URL):
    """Credential store stub that resolves `mattermost` and `mattermost_url`."""
    cred = MagicMock()
    cred.get.side_effect = lambda key: {"mattermost": token, "mattermost_url": url}.get(key)
    return cred


@pytest.fixture
def tools():
    return _register(credentials=_creds())


@patch("aden_tools.tools.mattermost_tool.mattermost_tool.httpx.request")
def test_send_message_success(mock_request, tools):
    mock_request.return_value = MagicMock(
        status_code=201,
        json=MagicMock(return_value={"id": "p1", "channel_id": "c1", "message": "hi"}),
    )
    result = tools["mattermost_send_message"]("c1", "hi")
    assert result["success"] is True
    assert result["post"]["message"] == "hi"


def test_send_message_length_validation(tools):
    """Oversize messages are rejected before we burn a Mattermost call."""
    result = tools["mattermost_send_message"]("c1", "x" * (MAX_MESSAGE_LENGTH + 1))
    assert "error" in result
    assert result["max_length"] == MAX_MESSAGE_LENGTH


@patch("aden_tools.tools.mattermost_tool.mattermost_tool.time.sleep")
@patch("aden_tools.tools.mattermost_tool.mattermost_tool.httpx.request")
def test_rate_limit_exhaustion_is_classified(mock_request, _mock_sleep, tools):
    """A storm of 429s exits the retry loop with an actionable error,
    not a stack trace. time.sleep is patched so the test stays fast."""
    mock_request.return_value = MagicMock(
        status_code=429,
        headers={"Retry-After": "5"},
        text="{}",
    )
    result = tools["mattermost_send_message"]("c1", "hi")
    assert "rate limit" in result["error"].lower()
    assert mock_request.call_count == MAX_RETRIES + 1


def test_missing_token_fails_loudly():
    tools = _register(credentials=_creds(token=None))
    with patch.dict("os.environ", {"MATTERMOST_ACCESS_TOKEN": ""}, clear=False):
        result = tools["mattermost_list_teams"]()
    assert "error" in result
    assert "not configured" in result["error"]


def test_missing_url_fails_loudly():
    """Mattermost needs URL too — missing URL must fail loudly, not
    silently target the wrong host."""
    tools = _register(credentials=_creds(url=None))
    with patch.dict("os.environ", {"MATTERMOST_URL": ""}, clear=False):
        result = tools["mattermost_list_teams"]()
    assert "error" in result
    assert "URL" in result["error"]


def test_credential_spec_registered():
    """Both the token spec and the URL spec are routed by the credential store."""
    from aden_tools.credentials import CREDENTIAL_SPECS

    token_spec = CREDENTIAL_SPECS["mattermost"]
    assert token_spec.env_var == "MATTERMOST_ACCESS_TOKEN"
    assert "mattermost_send_message" in token_spec.tools

    url_spec = CREDENTIAL_SPECS["mattermost_url"]
    assert url_spec.env_var == "MATTERMOST_URL"
