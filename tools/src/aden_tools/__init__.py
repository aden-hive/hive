"""
Aden Tools - Tool library for the Aden agent framework.

Tools provide capabilities that AI agents can use to interact with
external systems, process data, and perform actions.

Usage:
    from fastmcp import FastMCP
    from aden_tools.tools import register_all_tools
    from aden_tools.credentials import CredentialStoreAdapter

    mcp = FastMCP("my-server")
    credentials = CredentialStoreAdapter.default()
    register_all_tools(mcp, credentials=credentials)
"""

__version__ = "0.1.0"

# Credential management (no external dependencies)
from .credentials import (
    CREDENTIAL_SPECS,
    CredentialError,
    CredentialSpec,
    CredentialStoreAdapter,
)

# Utilities (no external dependencies)
from .utils import get_env_var


def __getattr__(name: str):
    """Lazy import for tools that require fastmcp."""
    if name == "register_all_tools":
        from .tools import register_all_tools

        return register_all_tools
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Version
    "__version__",
    # Utilities
    "get_env_var",
    # Credentials
    "CredentialStoreAdapter",
    "CredentialSpec",
    "CredentialError",
    "CREDENTIAL_SPECS",
    # MCP registration (lazy loaded)
    "register_all_tools",
]
