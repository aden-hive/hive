"""Credential validation utilities.

Provides reusable credential validation for agents, whether run through
the AgentRunner or directly via GraphExecutor.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def ensure_credential_key_env() -> None:
    """Load HIVE_CREDENTIAL_KEY and ADEN_API_KEY from shell config if not in environment.

    The setup-credentials skill writes these to ~/.zshrc or ~/.bashrc.
    If the user hasn't sourced their config in the current shell, this reads
    them directly so the runner (and any MCP subprocesses it spawns) can:
    - Unlock the encrypted credential store (HIVE_CREDENTIAL_KEY)
    - Enable Aden OAuth sync for Google/HubSpot/etc. (ADEN_API_KEY)
    """
    try:
        from aden_tools.credentials.shell_config import check_env_var_in_shell_config
    except ImportError:
        return

    for var_name in ("HIVE_CREDENTIAL_KEY", "ADEN_API_KEY"):
        if os.environ.get(var_name):
            continue
        found, value = check_env_var_in_shell_config(var_name)
        if found and value:
            os.environ[var_name] = value
            logger.debug("Loaded %s from shell config", var_name)


def validate_agent_credentials(nodes: list) -> None:
    """Check that required credentials are available before running an agent.

    Uses CredentialStoreAdapter.default() which includes Aden sync support,
    correctly resolving OAuth credentials stored under hashed IDs.

    Raises CredentialError with actionable guidance if any are missing.

    Args:
        nodes: List of NodeSpec objects from the agent graph.
    """
    required_tools: set[str] = set()
    for node in nodes:
        if node.tools:
            required_tools.update(node.tools)
    node_types: set[str] = {node.node_type for node in nodes}

    try:
        from aden_tools.credentials.store_adapter import CredentialStoreAdapter
    except ImportError:
        return  # aden_tools not installed, skip check

    ensure_credential_key_env()
    adapter = CredentialStoreAdapter.default()

    missing: list[str] = []

    # Check tool credentials
    for _cred_name, spec in adapter.get_missing_for_tools(sorted(required_tools)):
        affected = sorted(t for t in required_tools if t in spec.tools)
        entry = f"  {spec.env_var} for {', '.join(affected)}"
        if spec.help_url:
            entry += f"\n    Get it at: {spec.help_url}"
        missing.append(entry)

    # Check node type credentials (e.g., ANTHROPIC_API_KEY for LLM nodes)
    for _cred_name, spec in adapter.get_missing_for_node_types(sorted(node_types)):
        affected_types = sorted(t for t in node_types if t in spec.node_types)
        entry = f"  {spec.env_var} for {', '.join(affected_types)} nodes"
        if spec.help_url:
            entry += f"\n    Get it at: {spec.help_url}"
        missing.append(entry)

    if missing:
        from framework.credentials.models import CredentialError

        lines = ["Missing required credentials:\n"]
        lines.extend(missing)
        lines.append(
            "\nTo fix: run /hive-credentials in Claude Code."
            "\nIf you've already set up credentials, restart your terminal to load them."
        )
        raise CredentialError("\n".join(lines))
