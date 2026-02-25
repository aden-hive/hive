"""Tests for Tier 1 and Tier 2 tool resolution.

Tier 1: tools=["web_search"]          — exact, credential must be set
Tier 2: tools=[["web_search", "exa"]] — fallback group, first with credential wins
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from framework.graph.node import NodeSpec
from framework.llm.provider import Tool, ToolUse
from framework.runner.tool_registry import ToolRegistry, _is_auth_error

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

CRED_SPECS_PATCH = {
    "brave_search": MagicMock(env_var="BRAVE_SEARCH_API_KEY", tools=["web_search"]),
    "exa_search": MagicMock(env_var="EXA_API_KEY", tools=["exa_search"]),
}


def _make_tool(name: str) -> Tool:
    return Tool(name=name, description="", parameters={"type": "object", "properties": {}})


def _make_executor(tools: list[Tool]):
    from framework.graph.executor import GraphExecutor

    return GraphExecutor(runtime=MagicMock(), llm=MagicMock(), tools=tools)


def _make_graph(node_tools: list):
    node = NodeSpec(
        id="node1",
        name="research",
        description="",
        node_type="event_loop",
        tools=node_tools,
    )
    graph = MagicMock()
    graph.nodes = [node]
    return graph


# ---------------------------------------------------------------------------
# _is_auth_error helper
# ---------------------------------------------------------------------------


def test_is_auth_error_detects_401():
    assert _is_auth_error("HTTP 401 Unauthorized") is True


def test_is_auth_error_detects_403():
    assert _is_auth_error("403 Forbidden") is True


def test_is_auth_error_detects_invalid_api_key():
    assert _is_auth_error("Invalid API key provided") is True


def test_is_auth_error_ignores_generic_error():
    assert _is_auth_error("No results found") is False


def test_is_auth_error_ignores_timeout():
    assert _is_auth_error("Connection timeout") is False


# ---------------------------------------------------------------------------
# NodeSpec.all_tool_names
# ---------------------------------------------------------------------------


def test_all_tool_names_tier1():
    spec = NodeSpec(
        id="n1",
        name="N1",
        description="",
        tools=["web_search", "github_search"],
    )
    assert spec.all_tool_names == ["web_search", "github_search"]


def test_all_tool_names_tier2():
    spec = NodeSpec(
        id="n1",
        name="N1",
        description="",
        tools=[["web_search", "exa_search"], "github_search"],
    )
    assert spec.all_tool_names == ["web_search", "exa_search", "github_search"]


def test_all_tool_names_empty():
    spec = NodeSpec(id="n1", name="N1", description="", tools=[])
    assert spec.all_tool_names == []


# ---------------------------------------------------------------------------
# Tier 1 — key missing → error before agent starts
# ---------------------------------------------------------------------------


@patch.dict(os.environ, {}, clear=True)
def test_tier1_key_missing_returns_error_message():
    """_validate_tools returns an error when Tier 1 tool credential is missing."""
    executor = _make_executor([_make_tool("web_search")])
    graph = _make_graph(["web_search"])

    with patch("aden_tools.credentials.CREDENTIAL_SPECS", CRED_SPECS_PATCH, create=True):
        errors = executor._validate_tools(graph)

    assert any("BRAVE_SEARCH_API_KEY" in e for e in errors), errors


@patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "valid-key"})
def test_tier1_key_present_no_error():
    """_validate_tools passes when Tier 1 tool credential is set."""
    executor = _make_executor([_make_tool("web_search")])
    graph = _make_graph(["web_search"])

    with patch("aden_tools.credentials.CREDENTIAL_SPECS", CRED_SPECS_PATCH, create=True):
        errors = executor._validate_tools(graph)

    assert errors == []
    assert executor._resolved_node_tools["node1"] == ["web_search"]


# ---------------------------------------------------------------------------
# Tier 2 — fallback resolution
# ---------------------------------------------------------------------------


@patch.dict(os.environ, {"EXA_API_KEY": "exa-key"})
def test_tier2_first_missing_resolves_to_second():
    """Tier 2: web_search skipped (key missing), exa_search used."""
    executor = _make_executor([_make_tool("web_search"), _make_tool("exa_search")])
    graph = _make_graph([["web_search", "exa_search"]])

    with patch("aden_tools.credentials.CREDENTIAL_SPECS", CRED_SPECS_PATCH, create=True):
        errors = executor._validate_tools(graph)

    assert errors == []
    assert executor._resolved_node_tools["node1"] == ["exa_search"]


@patch.dict(os.environ, {}, clear=True)
def test_tier2_all_keys_missing_errors():
    """Tier 2: no tool in group has credentials → error before agent starts."""
    executor = _make_executor([_make_tool("web_search"), _make_tool("exa_search")])
    graph = _make_graph([["web_search", "exa_search"]])

    with patch("aden_tools.credentials.CREDENTIAL_SPECS", CRED_SPECS_PATCH, create=True):
        errors = executor._validate_tools(graph)

    assert len(errors) == 1
    assert "no tool in" in errors[0]


@patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "brave-key"})
def test_tier2_first_present_uses_first():
    """Tier 2: web_search has credential → uses web_search, no fallback needed."""
    executor = _make_executor([_make_tool("web_search"), _make_tool("exa_search")])
    graph = _make_graph([["web_search", "exa_search"]])

    with patch("aden_tools.credentials.CREDENTIAL_SPECS", CRED_SPECS_PATCH, create=True):
        errors = executor._validate_tools(graph)

    assert errors == []
    assert executor._resolved_node_tools["node1"] == ["web_search"]


# ---------------------------------------------------------------------------
# Runtime: credential_error flag stops the agent
# ---------------------------------------------------------------------------


def test_credential_error_flag_in_tool_result():
    """get_executor tags auth errors with credential_error: True."""
    registry = ToolRegistry()

    def bad_executor(_inputs):
        raise RuntimeError("401 Unauthorized: invalid API key")

    registry.register("web_search", _make_tool("web_search"), bad_executor)
    executor_fn = registry.get_executor()

    result = executor_fn(ToolUse(id="t1", name="web_search", input={}))

    assert result.is_error is True
    parsed = json.loads(result.content)
    assert parsed.get("credential_error") is True


def test_non_auth_error_no_credential_flag():
    """get_executor does NOT tag non-auth errors with credential_error."""
    registry = ToolRegistry()

    def bad_executor(_inputs):
        raise RuntimeError("No results found for query")

    registry.register("web_search", _make_tool("web_search"), bad_executor)
    executor_fn = registry.get_executor()

    result = executor_fn(ToolUse(id="t1", name="web_search", input={}))

    assert result.is_error is True
    parsed = json.loads(result.content)
    assert "credential_error" not in parsed


# ---------------------------------------------------------------------------
# Backward compat: Tier 1 plain string still works
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tool_decl",
    [
        ["web_search"],
        [["web_search", "exa_search"]],
    ],
)
def test_all_tool_names_is_always_flat(tool_decl):
    """all_tool_names always returns a flat list regardless of tier."""
    spec = NodeSpec(id="n1", name="N1", description="", tools=tool_decl)
    for name in spec.all_tool_names:
        assert isinstance(name, str)
