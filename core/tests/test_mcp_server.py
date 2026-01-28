"""
Smoke tests for the MCP server module.
"""

import pytest


def _mcp_available() -> bool:
    """Check if MCP dependencies are installed."""
    try:
        import mcp  # noqa: F401
        from mcp.server import FastMCP  # noqa: F401

        return True
    except ImportError:
        return False


MCP_AVAILABLE = _mcp_available()
MCP_SKIP_REASON = "MCP dependencies not installed"


class TestMCPDependencies:
    """Tests for MCP dependency availability."""

    def test_mcp_package_available(self):
        """Test that the mcp package can be imported."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        import mcp

        assert mcp is not None

    def test_fastmcp_available(self):
        """Test that FastMCP class is available from mcp server."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        from mcp.server import FastMCP

        assert FastMCP is not None


class TestAgentBuilderServerModule:
    """Tests for the agent_builder_server module."""

    def test_module_importable(self):
        """Test that framework.mcp.agent_builder_server can be imported."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        import framework.mcp.agent_builder_server as module

        assert module is not None

    def test_mcp_object_exported(self):
        """Test that the module exports the 'mcp' object (FastMCP instance)."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        from mcp.server import FastMCP

        from framework.mcp.agent_builder_server import mcp

        assert mcp is not None
        assert isinstance(mcp, FastMCP)

    def test_mcp_server_name(self):
        """Test that the MCP server has the expected name."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        from framework.mcp.agent_builder_server import mcp

        assert mcp.name == "agent-builder"


class TestMCPPackageExports:
    """Tests for the framework.mcp package exports."""

    def test_package_importable(self):
        """Test that framework.mcp package can be imported."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        import framework.mcp

        assert framework.mcp is not None

    def test_agent_builder_server_exported(self):
        """Test that agent_builder_server is exported from framework.mcp."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        from mcp.server import FastMCP

        from framework.mcp import agent_builder_server

        assert agent_builder_server is not None
        assert isinstance(agent_builder_server, FastMCP)
