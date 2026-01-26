"""
Centralized credential management for Aden Tools.

Provides agent-aware validation, clear error messages, and testability.

Philosophy: Google Strictness + Apple UX
- Validate credentials before running an agent (fail-fast at the right boundary)
- Guided error messages with clear next steps

Usage:
    # In mcp_server.py (startup validation)
    credentials = CredentialManager()
    credentials.validate_startup()

    # In agent runner (validate at agent load time)
    credentials.validate_for_tools(["web_search", "file_read"])

    # In tools
    api_key = credentials.get("brave_search")

    # In tests
    creds = CredentialManager.for_testing({"brave_search": "test-key"})

Credential categories:
- llm.py: LLM provider credentials (anthropic, openai, etc.)
- search.py: Search tool credentials (brave_search, google_search, etc.)

To add a new credential:
1. Find the appropriate category file (or create a new one)
2. Add the CredentialSpec to that file's dictionary
3. If new category, import and merge it in this __init__.py
"""
from .base import CredentialError, CredentialManager, CredentialSpec
from .llm import LLM_CREDENTIALS
from .search import SEARCH_CREDENTIALS

# Merged registry of all credentials
CREDENTIAL_SPECS = {
    **LLM_CREDENTIALS,
    **SEARCH_CREDENTIALS,
}

__all__ = [
    # Core classes
    "CredentialSpec",
    "CredentialManager",
    "CredentialError",
    # Merged registry
    "CREDENTIAL_SPECS",
    # Category registries (for direct access if needed)
    "LLM_CREDENTIALS",
    "SEARCH_CREDENTIALS",
]
