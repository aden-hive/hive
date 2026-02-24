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
    """Load credentials from shell config if not in environment.

    The quickstart.sh and setup-credentials skill write API keys to ~/.zshrc
    or ~/.bashrc. If the user hasn't sourced their config in the current shell,
    this reads them directly so the runner (and any MCP subprocesses) can use them.

    Loads:
    - HIVE_CREDENTIAL_KEY (encrypted credential store)
    - ADEN_API_KEY (Aden OAuth sync)
    - All LLM API keys (ANTHROPIC_API_KEY, OPENAI_API_KEY, ZAI_API_KEY, etc.)
    """
    try:
        from aden_tools.credentials.shell_config import check_env_var_in_shell_config
    except ImportError:
        return

    # Core credentials that are always checked
    env_vars_to_load = ["HIVE_CREDENTIAL_KEY", "ADEN_API_KEY"]

    # Add all LLM/tool API keys from CREDENTIAL_SPECS
    try:
        from aden_tools.credentials import CREDENTIAL_SPECS

        for spec in CREDENTIAL_SPECS.values():
            if spec.env_var and spec.env_var not in env_vars_to_load:
                env_vars_to_load.append(spec.env_var)
    except ImportError:
        pass

    for var_name in env_vars_to_load:
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


def _presync_aden_tokens(credential_specs: dict) -> None:
    """Sync Aden-backed OAuth tokens into env vars for validation.

    When ADEN_API_KEY is available, fetches fresh OAuth tokens from the Aden
    server and exports them to env vars.  This ensures validation sees real
    tokens instead of stale or mis-stored values in the encrypted store.
    Only touches credentials that are ``aden_supported`` AND whose env var
    is not already set (so explicit user exports always win).
    """
    from framework.credentials.store import CredentialStore

    try:
        aden_store = CredentialStore.with_aden_sync(auto_sync=True)
    except Exception as e:
        logger.warning("Aden pre-sync unavailable: %s", e)
        return

    for name, spec in credential_specs.items():
        if not spec.aden_supported:
            continue
        if os.environ.get(spec.env_var):
            continue  # Already set — don't overwrite
        cred_id = spec.credential_id or name
        try:
            value = aden_store.get_key(cred_id, spec.credential_key)
            if value:
                os.environ[spec.env_var] = value
                logger.debug("Pre-synced %s from Aden", spec.env_var)
            else:
                logger.warning(
                    "Pre-sync: %s (id=%s) available but key '%s' returned None",
                    spec.env_var,
                    cred_id,
                    spec.credential_key,
                )
        except Exception as e:
            logger.warning(
                "Pre-sync failed for %s (id=%s): %s",
                spec.env_var,
                cred_id,
                e,
            )


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
    #
    # Pre-sync: when ADEN_API_KEY is available, sync OAuth tokens from Aden
    # into env vars so validation sees fresh tokens instead of stale values
    # in the encrypted store (e.g., a previously mis-stored google.enc).
    if os.environ.get("ADEN_API_KEY"):
        _presync_aden_tokens(CREDENTIAL_SPECS)

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
    # Aden-backed creds where ADEN_API_KEY is set but integration not connected
    aden_not_connected: list[str] = []
    failed_cred_names: list[str] = []  # all cred names that need (re-)collection
    has_aden_key = bool(os.environ.get("ADEN_API_KEY"))
    checked: set[str] = set()
    # Credentials that are present and should be health-checked
    to_verify: list[tuple[str, str]] = []  # (cred_name, used_by_label)

    def _check_credential(spec, cred_name: str, label: str) -> None:
        cred_id = spec.credential_id or cred_name
        if not store.is_available(cred_id):
            # If ADEN_API_KEY is set and this is an Aden-only credential,
            # the issue is that the integration isn't connected on hive.adenhq.com,
            # NOT that the user needs to re-enter ADEN_API_KEY.
            if has_aden_key and spec.aden_supported and not spec.direct_api_key_supported:
                aden_not_connected.append(
                    f"  {spec.env_var} for {label}"
                    f"\n    Connect this integration at hive.adenhq.com first."
                )
            else:
                entry = f"  {spec.env_var} for {label}"
                if spec.help_url:
                    entry += f"\n    Get it at: {spec.help_url}"
                missing.append(entry)
                failed_cred_names.append(cred_name)
        elif verify and spec.health_check_endpoint:
            to_verify.append((cred_name, label))

    # Check tool credentials
    for tool_name in sorted(required_tools):
        cred_name = tool_to_cred.get(tool_name)
        if cred_name is None or cred_name in checked:
            continue
        checked.add(cred_name)
        spec = CREDENTIAL_SPECS[cred_name]
        if not spec.required:
            continue
        affected = sorted(t for t in required_tools if t in spec.tools)
        label = ", ".join(affected)
        _check_credential(spec, cred_name, label)

    # Check node type credentials (e.g., ANTHROPIC_API_KEY for LLM nodes)
    for nt in sorted(node_types):
        cred_name = node_type_to_cred.get(nt)
        if cred_name is None or cred_name in checked:
            continue
        checked.add(cred_name)
        spec = CREDENTIAL_SPECS[cred_name]
        if not spec.required:
            continue
        affected_types = sorted(t for t in node_types if t in spec.node_types)
        label = ", ".join(affected_types) + " nodes"
        _check_credential(spec, cred_name, label)

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
                        failed_cred_names.append(cred_name)
                    elif result.valid:
                        # Persist identity from health check (best-effort)
                        identity_data = result.details.get("identity")
                        if identity_data and isinstance(identity_data, dict):
                            try:
                                cred_obj = store.get_credential(cred_id, refresh_if_needed=False)
                                if cred_obj:
                                    cred_obj.set_identity(**identity_data)
                                    store.save_credential(cred_obj)
                            except Exception:
                                pass  # Identity persistence is best-effort
                except Exception as exc:
                    logger.debug("Health check for %s failed: %s", cred_name, exc)

    errors = missing + invalid + aden_not_connected
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
        if aden_not_connected:
            if missing or invalid:
                lines.append("")
            lines.append(
                "Aden integrations not connected "
                "(ADEN_API_KEY is set but OAuth tokens unavailable):\n"
            )
            lines.extend(aden_not_connected)
        lines.append(
            "\nTo fix: run /hive-credentials in Claude Code."
            "\nIf you've already set up credentials, "
            "restart your terminal to load them."
        )
        exc = CredentialError("\n".join(lines))
        exc.failed_cred_names = failed_cred_names  # type: ignore[attr-defined]
        raise exc


def build_setup_session_from_error(
    credential_error: Exception,
    nodes: list | None = None,
    agent_path: str | None = None,
):
    """Build a ``CredentialSetupSession`` that covers all failed credentials.

    ``validate_agent_credentials`` attaches ``failed_cred_names`` (both missing
    and invalid) to the ``CredentialError``.  This helper converts those names
    into ``MissingCredential`` entries so the setup screen can re-collect them.

    Falls back to the normal ``from_nodes`` / ``from_agent_path`` detection
    when the attribute is absent.

    Args:
        credential_error: The ``CredentialError`` raised by validation.
        nodes: Graph nodes (preferred — avoids re-loading from disk).
        agent_path: Agent directory path (used when nodes aren't available).
    """
    from framework.credentials.setup import CredentialSetupSession, MissingCredential

    # Start with normal detection (picks up truly missing creds)
    if nodes is not None:
        session = CredentialSetupSession.from_nodes(nodes)
    elif agent_path is not None:
        session = CredentialSetupSession.from_agent_path(agent_path)
    else:
        session = CredentialSetupSession(missing=[])

    # Add credentials that are present but failed health checks
    already = {m.credential_name for m in session.missing}
    failed_names: list[str] = getattr(credential_error, "failed_cred_names", [])
    if failed_names:
        try:
            from aden_tools.credentials import CREDENTIAL_SPECS

            for name in failed_names:
                if name in already:
                    continue
                spec = CREDENTIAL_SPECS.get(name)
                if spec is None:
                    continue
                session.missing.append(
                    MissingCredential(
                        credential_name=name,
                        env_var=spec.env_var,
                        description=spec.description,
                        help_url=spec.help_url,
                        api_key_instructions=spec.api_key_instructions,
                        tools=list(spec.tools),
                        aden_supported=spec.aden_supported,
                        direct_api_key_supported=spec.direct_api_key_supported,
                        credential_id=spec.credential_id,
                        credential_key=spec.credential_key,
                    )
                )
        except ImportError:
            pass

    return session
