"""
Aden Tools - Tool library for the Aden agent framework.

Tools provide capabilities that AI agents can use to interact with
external systems, process data, and perform actions.

Usage:
    from fastmcp import FastMCP
    from aden_tools.tools import register_all_tools
    from aden_tools.credentials import CredentialManager

    mcp = FastMCP("my-server")
    credentials = CredentialManager()
    register_all_tools(mcp, credentials=credentials)
"""

__version__ = "0.1.0"

# Utilities
from .utils import get_env_var

# Credential management
from .credentials import (
    CredentialManager,
    CredentialSpec,
    CredentialError,
    CREDENTIAL_SPECS,
)

# MCP registration
from .tools import register_all_tools

__all__ = [
    # Version
    "__version__",
    # Utilities
    "get_env_var",
    # Credentials
    "CredentialManager",
    "CredentialSpec",
    "CredentialError",
    "CREDENTIAL_SPECS",
    # MCP registration
    "register_all_tools",
]
