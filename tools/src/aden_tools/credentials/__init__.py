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
- email.py: Email provider credentials (resend, google/gmail)
- apollo.py: Apollo.io API credentials
- discord.py: Discord bot credentials
- github.py: GitHub API credentials
- hubspot.py: HubSpot CRM credentials
- slack.py: Slack workspace credentials
- google_maps.py: Google Maps Platform credentials
- calcom.py: Cal.com scheduling API credentials

Note: Tools that don't need credentials simply omit the 'credentials' parameter
from their register_tools() function. This convention is enforced by CI tests.

To add a new credential:
1. Find the appropriate category file (or create a new one)
2. Add the CredentialSpec to that file's dictionary
3. If new category, import and merge it in this __init__.py
"""

from .apollo import APOLLO_CREDENTIALS
from .base import CredentialError, CredentialSpec
from .bigquery import BIGQUERY_CREDENTIALS
from .brevo import BREVO_CREDENTIALS
from .browser import get_aden_auth_url, get_aden_setup_url, open_browser
from .calcom import CALCOM_CREDENTIALS
from .discord import DISCORD_CREDENTIALS
from .email import EMAIL_CREDENTIALS
from .gcp_vision import GCP_VISION_CREDENTIALS
from .github import GITHUB_CREDENTIALS
from .google_calendar import GOOGLE_CALENDAR_CREDENTIALS
from .google_docs import GOOGLE_DOCS_CREDENTIALS
from .google_maps import GOOGLE_MAPS_CREDENTIALS
from .health_check import (
    BaseHttpHealthChecker,
    HealthCheckResult,
    check_credential_health,
    validate_integration_wiring,
)
from .hubspot import HUBSPOT_CREDENTIALS
from .llm import LLM_CREDENTIALS
from .news import NEWS_CREDENTIALS
from .postgres import POSTGRES_CREDENTIALS
from .razorpay import RAZORPAY_CREDENTIALS
from .search import SEARCH_CREDENTIALS
from .serpapi import SERPAPI_CREDENTIALS
from .shell_config import (
    add_env_var_to_shell_config,
    detect_shell,
    get_shell_config_path,
    get_shell_source_command,
)
from .slack import SLACK_CREDENTIALS
from .store_adapter import CredentialStoreAdapter
from .stripe import STRIPE_CREDENTIALS
from .telegram import TELEGRAM_CREDENTIALS

# Merged registry of all credentials
CREDENTIAL_SPECS = {
    **LLM_CREDENTIALS,
    **NEWS_CREDENTIALS,
    **SEARCH_CREDENTIALS,
    **EMAIL_CREDENTIALS,
    **GCP_VISION_CREDENTIALS,
    **APOLLO_CREDENTIALS,
    **DISCORD_CREDENTIALS,
    **GITHUB_CREDENTIALS,
    **GOOGLE_DOCS_CREDENTIALS,
    **GOOGLE_MAPS_CREDENTIALS,
    **HUBSPOT_CREDENTIALS,
    **GOOGLE_CALENDAR_CREDENTIALS,
    **SLACK_CREDENTIALS,
    **SERPAPI_CREDENTIALS,
    **RAZORPAY_CREDENTIALS,
    **TELEGRAM_CREDENTIALS,
    **BIGQUERY_CREDENTIALS,
    **CALCOM_CREDENTIALS,
    **STRIPE_CREDENTIALS,
    **BREVO_CREDENTIALS,
    **POSTGRES_CREDENTIALS,
}

__all__ = [
    # Core classes
    "CredentialSpec",
    "CredentialStoreAdapter",
    "CredentialError",
    # Credential store adapter (replaces deprecated CredentialManager)
    "CredentialStoreAdapter",
    # Health check utilities
    "BaseHttpHealthChecker",
    "HealthCheckResult",
    "check_credential_health",
    "validate_integration_wiring",
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
    "NEWS_CREDENTIALS",
    "SEARCH_CREDENTIALS",
    "EMAIL_CREDENTIALS",
    "GCP_VISION_CREDENTIALS",
    "GITHUB_CREDENTIALS",
    "GOOGLE_DOCS_CREDENTIALS",
    "GOOGLE_MAPS_CREDENTIALS",
    "HUBSPOT_CREDENTIALS",
    "GOOGLE_CALENDAR_CREDENTIALS",
    "SLACK_CREDENTIALS",
    "APOLLO_CREDENTIALS",
    "SERPAPI_CREDENTIALS",
    "RAZORPAY_CREDENTIALS",
    "TELEGRAM_CREDENTIALS",
    "BIGQUERY_CREDENTIALS",
    "CALCOM_CREDENTIALS",
    "DISCORD_CREDENTIALS",
    "STRIPE_CREDENTIALS",
    "BREVO_CREDENTIALS",
    "POSTGRES_CREDENTIALS",
]
