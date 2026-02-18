"""Credential validation utilities.

Provides reusable credential validation for agents, whether run through
the AgentRunner or directly via GraphExecutor.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def ensure_credential_key_env() -> None:
    """Load HIVE_CREDENTIAL_KEY from shell config if not already in environment.

    The setup-credentials skill writes the encryption key to ~/.zshrc or ~/.bashrc.
    If the user hasn't sourced their config in the current shell, this reads it
    directly so the runner (and any MCP subprocesses it spawns) can unlock the
    encrypted credential store.

    Only HIVE_CREDENTIAL_KEY is loaded this way — all other secrets (API keys, etc.)
    come from the credential store itself.
    """
    if os.environ.get("HIVE_CREDENTIAL_KEY"):
        return

    try:
        from aden_tools.credentials.shell_config import check_env_var_in_shell_config

        found, value = check_env_var_in_shell_config("HIVE_CREDENTIAL_KEY")
        if found and value:
            os.environ["HIVE_CREDENTIAL_KEY"] = value
            logger.debug("Loaded HIVE_CREDENTIAL_KEY from shell config")
    except ImportError:
        pass


def validate_agent_credentials(nodes: list) -> None:
    """Check that required credentials are available before running an agent.

    Scans node specs for required tools and node types, then checks whether
    the corresponding credentials exist in the credential store.

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
        from aden_tools.credentials import CREDENTIAL_SPECS

        from framework.credentials import CredentialStore
        from framework.credentials.storage import (
            CompositeStorage,
            EncryptedFileStorage,
            EnvVarStorage,
        )
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
        lines.extend(missing)
        lines.append(
            "\nTo fix: run /hive-credentials in Claude Code."
            "\nIf you've already set up credentials, restart your terminal to load them."
        )
        raise CredentialError("\n".join(lines))
