"""Credential validation utilities.

Provides reusable credential validation for agents, whether run through
the AgentRunner or directly via GraphExecutor.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

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


@dataclass
class _CredentialCheck:
    """Result of checking a single credential."""

    env_var: str
    source: str
    used_by: str
    available: bool
    help_url: str = ""


def validate_agent_credentials(nodes: list, quiet: bool = False) -> None:
    """Check that required credentials are available before running an agent.

    Uses CredentialStoreAdapter.default() which includes Aden sync support,
    correctly resolving OAuth credentials stored under hashed IDs.

    Prints a summary of all credentials and their sources (encrypted store, env var).
    Raises CredentialError with actionable guidance if any are missing.

    Args:
        nodes: List of NodeSpec objects from the agent graph.
        quiet: If True, suppress the credential summary output.
    """
    # Collect required tools and node types
    required_tools = {tool for node in nodes if node.tools for tool in node.tools}
    node_types = {node.node_type for node in nodes}

    try:
        from aden_tools.credentials.store_adapter import CredentialStoreAdapter
    except ImportError:
        return  # aden_tools not installed, skip check

    # Build credential store
    env_mapping = {
        (spec.credential_id or name): spec.env_var for name, spec in CREDENTIAL_SPECS.items()
    }
    storages: list = [EnvVarStorage(env_mapping=env_mapping)]
    if os.environ.get("HIVE_CREDENTIAL_KEY"):
        storages.insert(0, EncryptedFileStorage())
    if len(storages) == 1:
        storage = storages[0]
    else:
        storage = CompositeStorage(primary=storages[0], fallbacks=storages[1:])
    store = CredentialStore(storage=storage)

    # Build reverse mappings
    tool_to_cred: dict[str, str] = {}
    node_type_to_cred: dict[str, str] = {}
    for cred_name, spec in CREDENTIAL_SPECS.items():
        for tool_name in spec.tools:
            tool_to_cred[tool_name] = cred_name
        for nt in spec.node_types:
            node_type_to_cred[nt] = cred_name

    missing: list[str] = []
    checked: set[str] = set()

    # Check tool credentials
    for tool_name in sorted(required_tools):
        cred_name = tool_to_cred.get(tool_name)
        if cred_name is None or cred_name in checked:
            continue
        checked.add(cred_name)
        spec = CREDENTIAL_SPECS[cred_name]
        cred_id = spec.credential_id or cred_name
        if spec.required and not store.is_available(cred_id):
            affected = sorted(t for t in required_tools if t in spec.tools)
            entry = f"  {spec.env_var} for {', '.join(affected)}"
            if spec.help_url:
                entry += f"\n    Get it at: {spec.help_url}"
            missing.append(entry)

    # Check node type credentials (e.g., ANTHROPIC_API_KEY for LLM nodes)
    for nt in sorted(node_types):
        cred_name = node_type_to_cred.get(nt)
        if cred_name is None or cred_name in checked:
            continue
        checked.add(cred_name)
        spec = CREDENTIAL_SPECS[cred_name]
        cred_id = spec.credential_id or cred_name
        if spec.required and not store.is_available(cred_id):
            affected_types = sorted(t for t in node_types if t in spec.node_types)
            entry = f"  {spec.env_var} for {', '.join(affected_types)} nodes"
            if spec.help_url:
                entry += f"\n    Get it at: {spec.help_url}"
            missing.append(entry)

    if missing:
        from framework.credentials.models import CredentialError

        lines = ["Missing required credentials:\n"]
        for c in missing:
            lines.append(f"  {c.env_var} for {c.used_by}")
            if c.help_url:
                lines.append(f"    Get it at: {c.help_url}")
        lines.append(
            "\nTo fix: run /hive-credentials in Claude Code."
            "\nIf you've already set up credentials, restart your terminal to load them."
        )
        raise CredentialError("\n".join(lines))
