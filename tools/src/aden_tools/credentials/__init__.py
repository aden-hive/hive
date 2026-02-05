"""
Centralized credential management for Aden Tools.

Provides agent-aware validation, clear error messages, and testability.

Philosophy: Google Strictness + Apple UX
- Validate credentials before running an agent (fail-fast at the right boundary)
- Guided error messages with clear next steps

Usage:
    from aden_tools.credentials import CredentialStoreAdapter
    from framework.credentials import CredentialStore

    # With encrypted storage (production)
    store = CredentialStore.with_encrypted_storage()  # defaults to ~/.hive/credentials
    credentials = CredentialStoreAdapter(store)

    # With composite storage (encrypted primary + env fallback)
    credentials = CredentialStoreAdapter.default()

    # In agent runner (validate at agent load time)
    credentials.validate_for_tools(["web_search", "file_read"])

    # In tools
    api_key = credentials.get("brave_search")

    # In tests
    creds = CredentialStoreAdapter.for_testing({"brave_search": "test-key"})

    # Template resolution
    headers = credentials.resolve_headers({
        "Authorization": "Bearer {{github_oauth.access_token}}"
    })

Credential categories:
- llm.py: LLM provider credentials (anthropic, openai, etc.)
- search.py: Search tool credentials (brave_search, google_search, etc.)
- integrations.py: Third-party integrations (hubspot, etc.)

To add a new credential:
1. Find the appropriate category file (or create a new one)
2. Add the CredentialSpec to that file's dictionary
3. If new category, import and merge it in this __init__.py
"""

from .base import CredentialError, CredentialSpec
from .browser import get_aden_auth_url, get_aden_setup_url, open_browser
from .email import EMAIL_CREDENTIALS
from .health_check import HealthCheckResult, check_credential_health
from .integrations import INTEGRATION_CREDENTIALS
from .llm import LLM_CREDENTIALS
from .search import SEARCH_CREDENTIALS
from .shell_config import (
    add_env_var_to_shell_config,
    detect_shell,
    get_shell_config_path,
    get_shell_source_command,
)
from .store_adapter import CredentialStoreAdapter

# Merged registry of all credentials
CREDENTIAL_SPECS = {
    **LLM_CREDENTIALS,
    **SEARCH_CREDENTIALS,
    **EMAIL_CREDENTIALS,
    **INTEGRATION_CREDENTIALS,
}

__all__ = [
    # Core classes
    "CredentialSpec",
    "CredentialStoreAdapter",
    "CredentialError",
    # Credential store adapter (replaces deprecated CredentialManager)
    "CredentialStoreAdapter",
    # Health check utilities
    "HealthCheckResult",
    "check_credential_health",
    # Browser utilities for OAuth2 flows
    "open_browser",
    "get_aden_auth_url",
    "get_aden_setup_url",
    # Shell config utilities
    "detect_shell",
    "get_shell_config_path",
    "get_shell_source_command",
    "add_env_var_to_shell_config",
    # Merged registry
    "CREDENTIAL_SPECS",
    # Category registries (for direct access if needed)
    "LLM_CREDENTIALS",
    "SEARCH_CREDENTIALS",
    "EMAIL_CREDENTIALS",
    "INTEGRATION_CREDENTIALS",
]
