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


def validate_agent_credentials(nodes: list, quiet: bool = False, verify: bool = True) -> None:
    """Check that required credentials are available and valid before running an agent.

    Two-phase validation:
    1. **Presence** — is the credential set (env var, encrypted store, or Aden sync)?
    2. **Health check** — does the credential actually work? Uses each tool's
       registered ``check_credential_health`` endpoint (lightweight HTTP call).

    Args:
        nodes: List of NodeSpec objects from the agent graph.
        quiet: If True, suppress the credential summary output.
        verify: If True (default), run health checks on present credentials.
    """
    # Collect required tools and node types
    required_tools = {tool for node in nodes if node.tools for tool in node.tools}
    node_types = {node.node_type for node in nodes}

    try:
        from aden_tools.credentials import CREDENTIAL_SPECS
    except ImportError:
        return  # aden_tools not installed, skip check

    from framework.credentials.storage import CompositeStorage, EncryptedFileStorage, EnvVarStorage
    from framework.credentials.store import CredentialStore

    # Build credential store.
    # Env vars take priority — if a user explicitly exports a fresh key it
    # must win over a potentially stale value in the encrypted store.
    env_mapping = {
        (spec.credential_id or name): spec.env_var for name, spec in CREDENTIAL_SPECS.items()
    }
    env_storage = EnvVarStorage(env_mapping=env_mapping)
    if os.environ.get("HIVE_CREDENTIAL_KEY"):
        storage = CompositeStorage(primary=env_storage, fallbacks=[EncryptedFileStorage()])
    else:
        storage = env_storage
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
    invalid: list[str] = []
    checked: set[str] = set()
    # Credentials that are present and should be health-checked
    to_verify: list[tuple[str, str]] = []  # (cred_name, used_by_label)

    # Check tool credentials
    for tool_name in sorted(required_tools):
        cred_name = tool_to_cred.get(tool_name)
        if cred_name is None or cred_name in checked:
            continue
        checked.add(cred_name)
        spec = CREDENTIAL_SPECS[cred_name]
        cred_id = spec.credential_id or cred_name
        if not spec.required:
            continue
        affected = sorted(t for t in required_tools if t in spec.tools)
        label = ", ".join(affected)
        if not store.is_available(cred_id):
            entry = f"  {spec.env_var} for {label}"
            if spec.help_url:
                entry += f"\n    Get it at: {spec.help_url}"
            missing.append(entry)
        elif verify and spec.health_check_endpoint:
            to_verify.append((cred_name, label))

    # Check node type credentials (e.g., ANTHROPIC_API_KEY for LLM nodes)
    for nt in sorted(node_types):
        cred_name = node_type_to_cred.get(nt)
        if cred_name is None or cred_name in checked:
            continue
        checked.add(cred_name)
        spec = CREDENTIAL_SPECS[cred_name]
        cred_id = spec.credential_id or cred_name
        if not spec.required:
            continue
        affected_types = sorted(t for t in node_types if t in spec.node_types)
        label = ", ".join(affected_types) + " nodes"
        if not store.is_available(cred_id):
            entry = f"  {spec.env_var} for {label}"
            if spec.help_url:
                entry += f"\n    Get it at: {spec.help_url}"
            missing.append(entry)
        elif verify and spec.health_check_endpoint:
            to_verify.append((cred_name, label))

    # Phase 2: health-check present credentials
    if to_verify:
        try:
            from aden_tools.credentials import check_credential_health
        except ImportError:
            check_credential_health = None  # type: ignore[assignment]

        if check_credential_health is not None:
            for cred_name, label in to_verify:
                spec = CREDENTIAL_SPECS[cred_name]
                cred_id = spec.credential_id or cred_name
                value = store.get(cred_id)
                if not value:
                    continue
                try:
                    result = check_credential_health(
                        cred_name,
                        value,
                        health_check_endpoint=spec.health_check_endpoint,
                        health_check_method=spec.health_check_method,
                    )
                    if not result.valid:
                        entry = f"  {spec.env_var} for {label} — {result.message}"
                        if spec.help_url:
                            entry += f"\n    Get a new key at: {spec.help_url}"
                        invalid.append(entry)
                except Exception as exc:
                    logger.debug("Health check for %s failed: %s", cred_name, exc)

    errors = missing + invalid
    if errors:
        from framework.credentials.models import CredentialError

        lines: list[str] = []
        if missing:
            lines.append("Missing credentials:\n")
            lines.extend(missing)
        if invalid:
            if missing:
                lines.append("")
            lines.append("Invalid or expired credentials:\n")
            lines.extend(invalid)
        lines.append(
            "\nTo fix: run /hive-credentials in Claude Code."
            "\nIf you've already set up credentials, restart your terminal to load them."
        )
        raise CredentialError("\n".join(lines))
