"""
Credential Tester — verify credentials (Aden OAuth + local API keys) via live API calls.

Interactive agent that lists all testable accounts, lets the user pick one,
loads the provider's tools, and runs a chat session to test the credential.
"""

from .agent import (
    CredentialTesterAgent,
    _list_aden_accounts,
    _list_env_fallback_accounts,
    _list_local_accounts,
    configure_for_account,
    conversation_mode,
    edges,
    entry_node,
    entry_points,
    get_tools_for_provider,
    goal,
    identity_prompt,
    list_connected_accounts,
    loop_config,
    nodes,
    pause_nodes,
    requires_account_selection,
    skip_credential_validation,
    skip_guardian,
    terminal_nodes,
)
from .config import default_config

__version__ = "1.0.0"

__all__ = [
    "CredentialTesterAgent",
    "configure_for_account",
    "conversation_mode",
    "default_config",
    "edges",
    "entry_node",
    "entry_points",
    "get_tools_for_provider",
    "goal",
    "identity_prompt",
    "list_connected_accounts",
    "loop_config",
    "nodes",
    "pause_nodes",
    "requires_account_selection",
    "skip_credential_validation",
    "skip_guardian",
    "terminal_nodes",
    # Internal list helpers (exposed for testing)
    "_list_aden_accounts",
    "_list_local_accounts",
    "_list_env_fallback_accounts",
]
