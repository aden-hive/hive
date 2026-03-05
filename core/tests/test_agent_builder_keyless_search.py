"""Tests for keyless search behavior in the MCP agent builder."""

from types import SimpleNamespace

import pytest


def _mcp_available() -> bool:
    try:
        import mcp  # noqa: F401
        from mcp.server import FastMCP  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _mcp_available(), reason="MCP dependencies not installed")
def test_normalize_exa_search_to_web_search():
    from framework.mcp.agent_builder_server import _normalize_tools_for_keyless_search

    tools, warnings = _normalize_tools_for_keyless_search(
        ["save_data", "exa_search", "web_scrape", "exa_search"]
    )
    assert tools == ["save_data", "web_search", "web_scrape"]
    assert any("Replaced tool 'exa_search' with 'web_search'" in w for w in warnings)


@pytest.mark.skipif(not _mcp_available(), reason="MCP dependencies not installed")
def test_validate_tool_credentials_skips_web_search(monkeypatch):
    from framework.mcp import agent_builder_server as builder

    # Force "no credentials available" in the store; web_search should still pass.
    monkeypatch.setattr(
        builder,
        "_get_credential_store",
        lambda: SimpleNamespace(is_available=lambda _k: False),
    )

    assert builder._validate_tool_credentials(["web_search"]) is None


@pytest.mark.skipif(not _mcp_available(), reason="MCP dependencies not installed")
def test_validate_tool_credentials_still_requires_exa(monkeypatch):
    from framework.mcp import agent_builder_server as builder

    monkeypatch.setattr(
        builder,
        "_get_credential_store",
        lambda: SimpleNamespace(is_available=lambda _k: False),
    )

    result = builder._validate_tool_credentials(["exa_search"])
    assert result is not None
    assert result["valid"] is False
    assert "missing_credentials" in result
