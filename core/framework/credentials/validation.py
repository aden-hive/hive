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

    Scans node specs for required tools and node types, then checks whether
    the corresponding credentials exist in the credential store.

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
        from aden_tools.credentials import CREDENTIAL_SPECS

        from framework.credentials import CredentialStore
        from framework.credentials.storage import (
            CompositeStorage,
            EncryptedFileStorage,
            EnvVarStorage,
        )
    except ImportError:
        return  # aden_tools not installed, skip check

    # Build storages
    env_mapping = {
        (spec.credential_id or name): spec.env_var for name, spec in CREDENTIAL_SPECS.items()
    }
    env_storage = EnvVarStorage(env_mapping=env_mapping)
    encrypted_storage = EncryptedFileStorage() if os.environ.get("HIVE_CREDENTIAL_KEY") else None

    if encrypted_storage:
        storage = CompositeStorage(primary=encrypted_storage, fallbacks=[env_storage])
    else:
        storage = env_storage
    store = CredentialStore(storage=storage)

    # Build reverse mappings: tool/node_type -> credential_name
    tool_to_cred = {tool: name for name, spec in CREDENTIAL_SPECS.items() for tool in spec.tools}
    node_type_to_cred = {
        nt: name for name, spec in CREDENTIAL_SPECS.items() for nt in spec.node_types
    }

    def get_source(cred_id: str) -> str:
        if encrypted_storage and encrypted_storage.exists(cred_id):
            return "encrypted store"
        if env_storage.exists(cred_id):
            return "environment variable"
        return "not found"

    def check_credential(cred_name: str, used_by: str) -> _CredentialCheck:
        spec = CREDENTIAL_SPECS[cred_name]
        cred_id = spec.credential_id or cred_name
        return _CredentialCheck(
            env_var=spec.env_var,
            source=get_source(cred_id),
            used_by=used_by,
            available=store.is_available(cred_id),
            help_url=spec.help_url,
        )

    # Check all credentials (deduplicated)
    checks: list[_CredentialCheck] = []
    checked: set[str] = set()

    for tool in sorted(required_tools):
        if (cred_name := tool_to_cred.get(tool)) and cred_name not in checked:
            checked.add(cred_name)
            spec = CREDENTIAL_SPECS[cred_name]
            affected = ", ".join(sorted(t for t in required_tools if t in spec.tools))
            checks.append(check_credential(cred_name, affected))

    for nt in sorted(node_types):
        if (cred_name := node_type_to_cred.get(nt)) and cred_name not in checked:
            checked.add(cred_name)
            spec = CREDENTIAL_SPECS[cred_name]
            affected = ", ".join(sorted(t for t in node_types if t in spec.node_types))
            checks.append(check_credential(cred_name, f"{affected} nodes"))

    # Print summary
    if not quiet and checks:
        print("\n📋 Credential Status:")
        print("-" * 60)
        for c in checks:
            status = "✓" if c.available else "✗"
            label = "Source" if c.available else "Required by"
            value = c.source if c.available else c.used_by
            suffix = "" if c.available else " (MISSING)"
            print(f"  {status} {c.env_var}{suffix}")
            print(f"      {label}: {value}")
            if c.available:
                print(f"      Used by: {c.used_by}")
        print("-" * 60)

    # Raise error if any missing
    missing = [c for c in checks if not c.available]
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
