"""Stage 1b: Registration tests.

Verifies that tool registration works correctly:
- register_tools(mcp) doesn't raise
- register_tools(mcp, credentials=mock_credentials) doesn't raise
- Expected tool names exist in mcp._tool_manager._tools
"""

from __future__ import annotations

import importlib
import inspect

import pytest
from fastmcp import FastMCP

from aden_tools.credentials import CredentialStoreAdapter

from .conftest import (
    CREDENTIAL_TOOL_MODULE_IDS,
    CREDENTIAL_TOOL_MODULES,
    MODULE_TO_TOOLS,
    TOOL_MODULE_IDS,
    TOOL_MODULES,
)

# ---------------------------------------------------------------------------
# 1b-1: register_tools(mcp) doesn't raise
# ---------------------------------------------------------------------------


class TestRegisterWithoutCredentials:
    """register_tools(mcp) must not raise for any tool module."""

    @pytest.mark.parametrize(
        "import_path,short_name",
        TOOL_MODULES,
        ids=TOOL_MODULE_IDS,
    )
    def test_register_tools_no_raise(self, import_path: str, short_name: str):
        """Calling register_tools(mcp) does not raise."""
        mod = importlib.import_module(import_path)
        mcp = FastMCP("test-reg")

        sig = inspect.signature(mod.register_tools)
        if "credentials" in sig.parameters:
            mod.register_tools(mcp, credentials=None)
        else:
            mod.register_tools(mcp)

        # Should complete without exception


# ---------------------------------------------------------------------------
# 1b-2: register_tools(mcp, credentials=mock) doesn't raise
# ---------------------------------------------------------------------------


class TestRegisterWithMockCredentials:
    """register_tools(mcp, credentials=mock) must not raise for credential tools."""

    @pytest.fixture
    def mock_credentials(self) -> CredentialStoreAdapter:
        """Create a CredentialStoreAdapter with all mock credentials."""
        return CredentialStoreAdapter.for_testing(
            {
                "anthropic": "test-anthropic-key",
                "brave_search": "test-brave-key",
                "google_search": "test-google-key",
                "google_cse": "test-google-cse-id",
                "resend": "test-resend-key",
                "github": "test-github-token",
                "hubspot": "test-hubspot-token",
            }
        )

    @pytest.mark.parametrize(
        "import_path,short_name",
        CREDENTIAL_TOOL_MODULES,
        ids=CREDENTIAL_TOOL_MODULE_IDS,
    )
    def test_register_tools_with_credentials_no_raise(
        self,
        import_path: str,
        short_name: str,
        mock_credentials: CredentialStoreAdapter,
    ):
        """Calling register_tools(mcp, credentials=mock) does not raise."""
        mod = importlib.import_module(import_path)
        mcp = FastMCP("test-reg-cred")
        mod.register_tools(mcp, credentials=mock_credentials)

        # Should complete without exception


# ---------------------------------------------------------------------------
# 1b-3: Expected tool names exist in mcp._tool_manager._tools
# ---------------------------------------------------------------------------


class TestExpectedToolsRegistered:
    """After registration, expected tool names must exist in the MCP instance."""

    @pytest.mark.parametrize(
        "import_path,short_name",
        TOOL_MODULES,
        ids=TOOL_MODULE_IDS,
    )
    def test_tools_registered_in_mcp(self, import_path: str, short_name: str):
        """The tool names registered by a module match expectations."""
        expected_tools = MODULE_TO_TOOLS.get(short_name, [])
        if not expected_tools:
            pytest.skip(f"No expected tools mapped for {short_name}")

        mod = importlib.import_module(import_path)
        mcp = FastMCP("test-tools")

        sig = inspect.signature(mod.register_tools)
        if "credentials" in sig.parameters:
            mod.register_tools(mcp, credentials=None)
        else:
            mod.register_tools(mcp)

        registered = set(mcp._tool_manager._tools.keys())
        for tool_name in expected_tools:
            assert tool_name in registered, (
                f"Tool '{tool_name}' expected from {short_name} "
                f"but not found. Registered: {sorted(registered)}"
            )

    def test_register_all_tools_returns_complete_list(self):
        """register_all_tools() return list matches actually registered tools."""
        from aden_tools.tools import register_all_tools

        mcp = FastMCP("test-all")
        returned_names = register_all_tools(mcp, credentials=None)
        registered = set(mcp._tool_manager._tools.keys())

        # Every returned name must actually be registered
        for name in returned_names:
            assert name in registered, (
                f"register_all_tools() lists '{name}' but it was not registered"
            )

        # Every registered tool must be in the return list
        for name in registered:
            assert name in returned_names, (
                f"Tool '{name}' is registered but not in register_all_tools() return list"
            )
