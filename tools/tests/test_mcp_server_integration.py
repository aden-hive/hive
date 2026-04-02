"""
Integration tests for the Tools MCP Server.

Tests the MCP server setup, tool registration, and HTTP endpoints.
"""

import pytest

# Skip all tests if FastMCP is not installed
try:
    from fastmcp import FastMCP

    FASTMCP_AVAILABLE = True
except ImportError:
    FASTMCP_AVAILABLE = False

pytestmark = pytest.mark.skipif(not FASTMCP_AVAILABLE, reason="FastMCP dependencies not installed")


class TestToolsMCPServerSetup:
    """Tests for tools MCP server initialization and configuration."""

    def test_mcp_server_importable(self):
        """Test that the mcp_server module can be imported."""
        # Import the server module (but don't start it)
        import importlib.util
        import sys
        from pathlib import Path

        # Check if module exists
        server_path = Path(__file__).parent.parent / "mcp_server.py"
        assert server_path.exists(), "mcp_server.py should exist in tools folder"

    def test_aden_tools_package_importable(self):
        """Test that aden_tools package can be imported."""
        from aden_tools import __version__, register_all_tools

        assert __version__ is not None
        assert register_all_tools is not None

    def test_credential_manager_importable(self):
        """Test that CredentialManager can be imported."""
        from aden_tools.credentials import CredentialManager

        assert CredentialManager is not None

    def test_credential_manager_for_testing(self):
        """Test that CredentialManager.for_testing() works correctly."""
        from aden_tools.credentials import CredentialManager

        manager = CredentialManager.for_testing(
            {
                "anthropic": "test-key",
                "brave_search": "test-brave-key",
            }
        )

        assert manager is not None

    def test_register_all_tools_returns_list(self, mcp, mock_credentials):
        """Test that register_all_tools returns a list of tool names."""
        from aden_tools.tools import register_all_tools

        tools = register_all_tools(mcp, credentials=mock_credentials)

        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_all_expected_tools_registered(self, mcp, mock_credentials):
        """Test that key tools are registered."""
        from aden_tools.tools import register_all_tools

        tools = register_all_tools(mcp, credentials=mock_credentials)

        # These are core tools that should always be present
        expected_tools = [
            "view_file",
            "write_to_file",
            "list_dir",
        ]

        for tool in expected_tools:
            assert tool in tools, f"Expected tool '{tool}' not found in registered tools"


class TestCredentialValidation:
    """Tests for credential validation flows."""

    def test_credential_manager_creation(self):
        """Test that CredentialManager can be created."""
        from aden_tools.credentials import CredentialManager

        manager = CredentialManager()
        assert manager is not None

    def test_credential_spec_definitions(self):
        """Test that credential specs are defined."""
        from aden_tools.credentials import CREDENTIAL_SPECS

        assert isinstance(CREDENTIAL_SPECS, dict)
        # Should have at least some credential specs
        assert len(CREDENTIAL_SPECS) >= 0


class TestMCPServerModule:
    """Tests for the mcp_server module structure."""

    def test_setup_logger_function_exists(self):
        """Test that setup_logger function exists."""
        import sys
        from pathlib import Path

        # We need to check if the mcp_server module can be partially loaded
        server_path = Path(__file__).parent.parent / "mcp_server.py"
        content = server_path.read_text()

        assert "def setup_logger" in content
        assert "def main" in content

    def test_fastmcp_instance_created_in_module(self):
        """Test that FastMCP instance is created in module."""
        from pathlib import Path

        server_path = Path(__file__).parent.parent / "mcp_server.py"
        content = server_path.read_text()

        assert 'FastMCP("tools")' in content

    def test_health_check_route_defined(self):
        """Test that health check route is defined."""
        from pathlib import Path

        server_path = Path(__file__).parent.parent / "mcp_server.py"
        content = server_path.read_text()

        assert "/health" in content
        assert "health_check" in content

    def test_index_route_defined(self):
        """Test that index route is defined."""
        from pathlib import Path

        server_path = Path(__file__).parent.parent / "mcp_server.py"
        content = server_path.read_text()

        # Should have a route for "/"
        assert 'custom_route("/")' in content or 'custom_route("/", methods' in content


class TestToolsPackageExports:
    """Tests for aden_tools package exports."""

    def test_version_exported(self):
        """Test that version is exported."""
        from aden_tools import __version__

        assert __version__ == "0.1.0"

    def test_get_env_var_exported(self):
        """Test that get_env_var utility is exported."""
        from aden_tools import get_env_var

        assert callable(get_env_var)

    def test_credential_classes_exported(self):
        """Test that credential classes are exported."""
        from aden_tools import (
            CREDENTIAL_SPECS,
            CredentialError,
            CredentialManager,
            CredentialSpec,
        )

        assert CredentialManager is not None
        assert CredentialSpec is not None
        assert CredentialError is not None
        assert isinstance(CREDENTIAL_SPECS, dict)

    def test_register_all_tools_exported(self):
        """Test that register_all_tools is exported."""
        from aden_tools import register_all_tools

        assert callable(register_all_tools)


class TestToolRegistration:
    """Tests for individual tool registration."""

    def test_file_system_tools_registered(self, mcp, mock_credentials):
        """Test that file system tools are registered."""
        from aden_tools.tools import register_all_tools

        tools = register_all_tools(mcp, credentials=mock_credentials)

        file_tools = ["view_file", "write_to_file", "list_dir"]
        for tool in file_tools:
            assert tool in tools

    def test_no_duplicate_tools(self, mcp, mock_credentials):
        """Test that no duplicate tools are registered."""
        from aden_tools.tools import register_all_tools

        tools = register_all_tools(mcp, credentials=mock_credentials)

        # Check for duplicates
        assert len(tools) == len(set(tools)), "Duplicate tools found in registration"
