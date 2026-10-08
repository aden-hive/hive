"""Smoke tests for the Discord tool.

Mock-based tests, so they can't catch wire-format drift against the real
Discord API — that's what the live suite is for. The goal here is to
defend a few outcomes that matter and would silently break:

- credentials → HTTP → success shape is wired end-to-end
- the client-side length guard rejects oversize messages without
  burning a Discord call
- a 429 storm produces a *classified* error, not a generic stack trace
- missing credentials fail loudly instead of hitting Discord with no token
- the credential spec is registered so the credential store routes
  `discord` to this tool
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aden_tools.tools.discord_tool.discord_tool import (
    MAX_MESSAGE_LENGTH,
    MAX_RETRIES,
    register_tools,
)


def _register(credentials=None):
    """Register Discord tools onto a stub MCP. Returns a name→fn lookup."""
    mcp = MagicMock()
    fns: dict[str, callable] = {}
    mcp.tool.return_value = lambda fn: fns.setdefault(fn.__name__, fn) or fn
    register_tools(mcp, credentials=credentials)
    return fns


@pytest.fixture
def tools():
    cred = MagicMock()
    cred.get.return_value = "test-token"
    return _register(credentials=cred)


@patch("aden_tools.tools.discord_tool.discord_tool.httpx.request")
def test_send_message_success(mock_request, tools):
    mock_request.return_value = MagicMock(
        status_code=200,
        json=MagicMock(return_value={"id": "m1", "channel_id": "c1", "content": "hi"}),
    )
    result = tools["discord_send_message"]("c1", "hi")
    assert result["success"] is True
    assert result["message"]["content"] == "hi"


def test_send_message_length_validation(tools):
    """Oversize messages are rejected before we burn a Discord call."""
    result = tools["discord_send_message"]("c1", "x" * (MAX_MESSAGE_LENGTH + 1))
    assert "error" in result
    assert result["max_length"] == MAX_MESSAGE_LENGTH


@patch("aden_tools.tools.discord_tool.discord_tool.time.sleep")
@patch("aden_tools.tools.discord_tool.discord_tool.httpx.request")
def test_rate_limit_exhaustion_is_classified(mock_request, _mock_sleep, tools):
    """A storm of 429s exits the retry loop with an actionable error,
    not a stack trace. time.sleep is patched so the test stays fast."""
    mock_request.return_value = MagicMock(
        status_code=429,
        json=MagicMock(return_value={"message": "Rate limit", "retry_after": 5}),
        text='{"message": "Rate limit", "retry_after": 5}',
    )
    result = tools["discord_send_message"]("c1", "hi")
    assert "rate limit" in result["error"].lower()
    assert result.get("retry_after") == 5
    assert mock_request.call_count == MAX_RETRIES + 1


def test_missing_credentials_fail_loudly():
    """No token configured → clear error, not a silent call to Discord."""
    tools = _register(credentials=None)
    with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": ""}, clear=False):
        result = tools["discord_list_guilds"]()
    assert "error" in result
    assert "not configured" in result["error"]


def test_credential_spec_registered():
    """The credential store routes `discord` to this tool's env var and
    publishes the tool names that need the token."""
    from aden_tools.credentials import CREDENTIAL_SPECS

    spec = CREDENTIAL_SPECS["discord"]
    assert spec.env_var == "DISCORD_BOT_TOKEN"
    assert "discord_send_message" in spec.tools
