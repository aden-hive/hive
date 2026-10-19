"""The email-senders suite is opt-in, and the gate is registration itself.

Senders are an advanced developer feature (desktop: Settings → Developer). The
gate is deliberately placed at MCP registration rather than at the queen's
allowlist: a tool that was never registered cannot be reached by ANY path — not
the prompt manifest, not `search_tools`, not a hand-edited tools.json, not the
allow-all fallback for unknown queens. With the flag off the model has no way
to learn the feature exists, which is the actual requirement; merely hiding the
Senders page while the tools stayed live would be a fake gate.

These tests fail if someone moves the check to a softer layer, or flips the
default to on.
"""

from __future__ import annotations

import pytest
from fastmcp import FastMCP

from aden_tools.tools import register_all_tools

# The nine tools that make up the suite (aden_tools.tools.senders_tool).
SENDER_TOOLS = frozenset(
    {
        "list_senders",
        "send_from_sender",
        "send_campaign",
        "setup_email_sender",
        "adjust_sender",
        "pick_sender",
        "sender_history",
        "suppress_recipient",
        "list_suppressed",
    }
)


def _registered(monkeypatch: pytest.MonkeyPatch, env: str | None) -> set[str]:
    """Tool names a fresh MCP server registers under the given env value."""
    if env is None:
        monkeypatch.delenv("HIVE_EMAIL_SENDERS", raising=False)
    else:
        monkeypatch.setenv("HIVE_EMAIL_SENDERS", env)
    return set(register_all_tools(FastMCP("test"), credentials=None, include_unverified=False))


def test_senders_absent_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """No env var — the suite must not be registered."""
    names = _registered(monkeypatch, None)
    assert not (SENDER_TOOLS & names)
    # Sanity: the rest of the catalog is intact, so an empty intersection above
    # means "senders are gated", not "registration blew up".
    assert "web_search" in names


@pytest.mark.parametrize("env", ["0", "false", "no", "off", ""])
def test_senders_absent_when_disabled(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    assert not (SENDER_TOOLS & _registered(monkeypatch, env))


@pytest.mark.parametrize("env", ["1", "true", "yes", "on", "TRUE"])
def test_senders_present_when_enabled(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    """Enabling restores the whole suite — a partial grant would be worse than none.

    (`send_from_sender` without `list_senders` would leave the model guessing at
    sender names it has no way to enumerate.)
    """
    assert SENDER_TOOLS <= _registered(monkeypatch, env)
