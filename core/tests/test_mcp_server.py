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


class TestMCPPackageExports:
    """Tests for the framework.mcp package exports."""

    def test_package_importable(self):
        """Test that framework.mcp package can be imported."""
        if not MCP_AVAILABLE:
            pytest.skip(MCP_SKIP_REASON)

        import framework.mcp

        assert framework.mcp is not None
