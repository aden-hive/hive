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
    """Load bootstrap credentials into ``os.environ``.

    Priority chain for each credential:
      1. ``os.environ`` (already set — nothing to do)
      2. Dedicated file storage (``~/.hive/secrets/`` or encrypted store)
      3. Shell config fallback (``~/.zshrc`` / ``~/.bashrc``) for backward compat

    Boot order matters: HIVE_CREDENTIAL_KEY must load BEFORE ADEN_API_KEY
    because the encrypted store depends on it.

    Remaining LLM/tool API keys still load from shell config.
    """
    from .key_storage import load_aden_api_key, load_credential_key

    # Step 1: HIVE_CREDENTIAL_KEY (must come first — encrypted store depends on it)
    load_credential_key()

    # Step 2: ADEN_API_KEY (uses encrypted store, then shell config fallback)
    load_aden_api_key()

    # Step 3: Load remaining LLM/tool API keys from shell config
    try:
        from aden_tools.credentials.shell_config import check_env_var_in_shell_config
    except ImportError:
        return

    try:
        from aden_tools.credentials import CREDENTIAL_SPECS

        for spec in CREDENTIAL_SPECS.values():
            var_name = spec.env_var
            if var_name and var_name not in ("HIVE_CREDENTIAL_KEY", "ADEN_API_KEY"):
                if not os.environ.get(var_name):
                    found, value = check_env_var_in_shell_config(var_name)
                    if found and value:
                        os.environ[var_name] = value
                        logger.debug("Loaded %s from shell config", var_name)
    except ImportError:
        pass


@dataclass
class CredentialStatus:
    """Status of a single required credential after validation."""

    credential_name: str
    credential_id: str
    env_var: str
    description: str
    help_url: str
    api_key_instructions: str
    tools: list[str]
    node_types: list[str]
    available: bool
    valid: bool | None  # None = not checked
    validation_message: str | None
    aden_supported: bool
    direct_api_key_supported: bool
    credential_key: str
    aden_not_connected: bool  # Aden-only cred, ADEN_API_KEY set, but integration missing
    alternative_group: str | None = None  # non-None when multiple providers can satisfy a tool


@dataclass
class CredentialValidationResult:
    """Result of validating all credentials required by an agent."""

    credentials: list[CredentialStatus]
    has_aden_key: bool

    @property
    def failed(self) -> list[CredentialStatus]:
        """Credentials that are missing, invalid, or Aden-not-connected.

        For alternative groups (multi-provider tools like send_email), the group
        is satisfied if ANY member is available and valid — only report failures
        when the entire group is unsatisfied.
        """
        # Check which alternative groups are satisfied
        alt_satisfied: dict[str, bool] = {}
        for c in self.credentials:
            if not c.alternative_group:
                continue
            if c.alternative_group not in alt_satisfied:
                alt_satisfied[c.alternative_group] = False
            if c.available and c.valid is not False:
                alt_satisfied[c.alternative_group] = True

        result = []
        for c in self.credentials:
            if c.alternative_group:
                # Skip if any alternative in the group is satisfied
                if alt_satisfied.get(c.alternative_group, False):
                    continue
                if not c.available or c.valid is False:
                    result.append(c)
            else:
                if not c.available or c.valid is False:
                    result.append(c)
        return result

    @property
    def has_errors(self) -> bool:
        return bool(self.failed)

    @property
    def failed_cred_names(self) -> list[str]:
        """Credential names that need (re-)collection, excluding Aden-not-connected."""
        return [c.credential_name for c in self.failed if not c.aden_not_connected]

    def format_error_message(self) -> str:
        """Format a human-readable error message for CLI/runner output."""
        missing = [c for c in self.credentials if not c.available and not c.aden_not_connected]
        invalid = [c for c in self.credentials if c.available and c.valid is False]
        aden_nc = [c for c in self.credentials if c.aden_not_connected]

        lines: list[str] = []
        if missing:
            lines.append("Missing credentials:\n")
            for c in missing:
                entry = f"  {c.env_var} for {_label(c)}"
                if c.help_url:
                    entry += f"\n    Get it at: {c.help_url}"
                lines.append(entry)
        if invalid:
            if missing:
                lines.append("")
            lines.append("Invalid or expired credentials:\n")
            for c in invalid:
                entry = f"  {c.env_var} for {_label(c)} — {c.validation_message}"
                if c.help_url:
                    entry += f"\n    Get a new key at: {c.help_url}"
                lines.append(entry)
        if aden_nc:
            if missing or invalid:
                lines.append("")
            lines.append(
                "Aden integrations not connected "
                "(ADEN_API_KEY is set but OAuth tokens unavailable):\n"
            )
            for c in aden_nc:
                lines.append(
                    f"  {c.env_var} for {_label(c)}"
                    f"\n    Connect this integration at hive.adenhq.com first."
                )
        lines.append(
            "\nTo fix: run /hive-credentials in Claude Code."
            "\nIf you've already set up credentials, "
            "restart your terminal to load them."
        )
        return "\n".join(lines)


def _label(c: CredentialStatus) -> str:
    """Build a human-readable label from tools/node_types."""
    if c.tools:
        return ", ".join(c.tools)
    if c.node_types:
        return ", ".join(c.node_types) + " nodes"
    return c.credential_name


def _presync_aden_tokens(credential_specs: dict, *, force: bool = False) -> None:
    """Sync Aden-backed OAuth tokens into env vars for validation.

    When ADEN_API_KEY is available, fetches fresh OAuth tokens from the Aden
    server and exports them to env vars.  This ensures validation sees real
    tokens instead of stale or mis-stored values in the encrypted store.
    Only touches credentials that are ``aden_supported`` AND whose env var
    is not already set (so explicit user exports always win).

    Args:
        force: When True, overwrite env vars that are already set.  Used by
            the credentials modal to pick up freshly reauthorized tokens
            from Aden instead of reusing stale values from a prior sync.
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
        if not force and os.environ.get(spec.env_var):
            continue  # Already set — don't overwrite
        cred_id = spec.credential_id or name
        # sync_all() already fetched everything available from Aden.
        # Skip credentials not in the store — they aren't connected,
        # so fetching individually would fail with "Invalid integration ID".
        if not aden_store.exists(cred_id):
            continue
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


def validate_agent_credentials(
    nodes: list,
    quiet: bool = False,
    verify: bool = True,
    raise_on_error: bool = True,
    force_refresh: bool = False,
) -> CredentialValidationResult:
    """Check that required credentials are available and valid before running an agent.

    Two-phase validation:
    1. **Presence** — is the credential set (env var, encrypted store, or Aden sync)?
    2. **Health check** — does the credential actually work? Uses each tool's
       registered ``check_credential_health`` endpoint (lightweight HTTP call).

    Args:
        nodes: List of NodeSpec objects from the agent graph.
        quiet: If True, suppress the credential summary output.
        verify: If True (default), run health checks on present credentials.
        raise_on_error: If True (default), raise CredentialError when validation
            fails.  Set to False to get the result without raising.
        force_refresh: If True, force re-sync of Aden OAuth tokens even when
            env vars are already set.  Used by the credentials modal after
            reauthorization.

    Returns:
        CredentialValidationResult with status of ALL required credentials.
    """
    empty_result = CredentialValidationResult(credentials=[], has_aden_key=False)

    # Collect required tools and node types
    required_tools: set[str] = set()
    node_types: set[str] = set()
    for node in nodes:
        if hasattr(node, "tools") and node.tools:
            required_tools.update(node.tools)
        if hasattr(node, "node_type"):
            node_types.add(node.node_type)

    try:
        from aden_tools.credentials import CREDENTIAL_SPECS
    except ImportError:
        return empty_result  # aden_tools not installed, skip check

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
        _presync_aden_tokens(CREDENTIAL_SPECS, force=force_refresh)

    env_mapping = {
        (spec.credential_id or name): spec.env_var for name, spec in CREDENTIAL_SPECS.items()
    }
    env_storage = EnvVarStorage(env_mapping=env_mapping)
    if os.environ.get("HIVE_CREDENTIAL_KEY"):
        storage = CompositeStorage(primary=env_storage, fallbacks=[EncryptedFileStorage()])
    else:
        storage = env_storage
    store = CredentialStore(storage=storage)

    # Build reverse mappings — 1:many for multi-provider tools (e.g. send_email → resend OR google)
    tool_to_creds: dict[str, list[str]] = {}
    node_type_to_cred: dict[str, str] = {}
    for cred_name, spec in CREDENTIAL_SPECS.items():
        for tool_name in spec.tools:
            tool_to_creds.setdefault(tool_name, []).append(cred_name)
        for nt in spec.node_types:
            node_type_to_cred[nt] = cred_name

    has_aden_key = bool(os.environ.get("ADEN_API_KEY"))
    checked: set[str] = set()
    all_credentials: list[CredentialStatus] = []
    # Credentials that are present and should be health-checked
    to_verify: list[int] = []  # indices into all_credentials

    def _check_credential(
        spec,
        cred_name: str,
        affected_tools: list[str],
        affected_node_types: list[str],
        alternative_group: str | None = None,
    ) -> None:
        cred_id = spec.credential_id or cred_name
        available = store.is_available(cred_id)

        # Aden-not-connected: ADEN_API_KEY set, Aden-only cred, but integration missing
        is_aden_nc = (
            not available
            and has_aden_key
            and spec.aden_supported
            and not spec.direct_api_key_supported
        )

        status = CredentialStatus(
            credential_name=cred_name,
            credential_id=cred_id,
            env_var=spec.env_var,
            description=spec.description,
            help_url=spec.help_url,
            api_key_instructions=getattr(spec, "api_key_instructions", ""),
            tools=affected_tools,
            node_types=affected_node_types,
            available=available,
            valid=None,
            validation_message=None,
            aden_supported=spec.aden_supported,
            direct_api_key_supported=spec.direct_api_key_supported,
            credential_key=spec.credential_key,
            aden_not_connected=is_aden_nc,
            alternative_group=alternative_group,
        )
        all_credentials.append(status)

        if available and verify and spec.health_check_endpoint:
            to_verify.append(len(all_credentials) - 1)

    # Check tool credentials
    for tool_name in sorted(required_tools):
        cred_names = tool_to_creds.get(tool_name)
        if cred_names is None:
            continue

        # Filter to credentials we haven't already checked
        unchecked = [cn for cn in cred_names if cn not in checked]
        if not unchecked:
            continue

        # Single provider — existing behavior
        if len(unchecked) == 1:
            cred_name = unchecked[0]
            checked.add(cred_name)
            spec = CREDENTIAL_SPECS[cred_name]
            if not spec.required:
                continue
            affected = sorted(t for t in required_tools if t in spec.tools)
            _check_credential(spec, cred_name, affected_tools=affected, affected_node_types=[])
            continue

        # Multi-provider (e.g. send_email → resend OR google):
        # satisfied if ANY provider credential is available.
        available_cn = None
        for cn in unchecked:
            spec = CREDENTIAL_SPECS[cn]
            cred_id = spec.credential_id or cn
            if store.is_available(cred_id):
                available_cn = cn
                break

        if available_cn is not None:
            # Found an available provider — check (and health-check) it
            checked.add(available_cn)
            spec = CREDENTIAL_SPECS[available_cn]
            affected = sorted(t for t in required_tools if t in spec.tools)
            _check_credential(spec, available_cn, affected_tools=affected, affected_node_types=[])
        else:
            # None available — report ALL alternatives so the modal can show them
            group_key = tool_name  # e.g. "send_email"
            for cn in unchecked:
                checked.add(cn)
                spec = CREDENTIAL_SPECS[cn]
                affected = sorted(t for t in required_tools if t in spec.tools)
                _check_credential(
                    spec,
                    cn,
                    affected_tools=affected,
                    affected_node_types=[],
                    alternative_group=group_key,
                )

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
        _check_credential(spec, cred_name, affected_tools=[], affected_node_types=affected_types)

    # Phase 2: health-check present credentials
    if to_verify:
        try:
            from aden_tools.credentials import check_credential_health
        except ImportError:
            check_credential_health = None  # type: ignore[assignment]

        if check_credential_health is not None:
            for idx in to_verify:
                status = all_credentials[idx]
                spec = CREDENTIAL_SPECS[status.credential_name]
                value = store.get(status.credential_id)
                if not value:
                    continue
                try:
                    result = check_credential_health(
                        status.credential_name,
                        value,
                        health_check_endpoint=spec.health_check_endpoint,
                        health_check_method=spec.health_check_method,
                    )
                    status.valid = result.valid
                    status.validation_message = result.message
                    if result.valid:
                        # Persist identity from health check (best-effort)
                        identity_data = result.details.get("identity")
                        if identity_data and isinstance(identity_data, dict):
                            try:
                                cred_obj = store.get_credential(
                                    status.credential_id, refresh_if_needed=False
                                )
                                if cred_obj:
                                    cred_obj.set_identity(**identity_data)
                                    store.save_credential(cred_obj)
                            except Exception:
                                pass  # Identity persistence is best-effort
                except Exception as exc:
                    logger.debug("Health check for %s failed: %s", status.credential_name, exc)

    validation_result = CredentialValidationResult(
        credentials=all_credentials,
        has_aden_key=has_aden_key,
    )

    if raise_on_error and validation_result.has_errors:
        from framework.credentials.models import CredentialError

        exc = CredentialError(validation_result.format_error_message())
        exc.validation_result = validation_result  # type: ignore[attr-defined]
        exc.failed_cred_names = validation_result.failed_cred_names  # type: ignore[attr-defined]
        raise exc

    return validation_result


def build_setup_session_from_error(
    credential_error: Exception,
    nodes: list | None = None,
    agent_path: str | None = None,
):
    """Build a ``CredentialSetupSession`` that covers all failed credentials.

    Uses the ``CredentialValidationResult`` attached to the ``CredentialError``
    when available.  Falls back to re-detecting from nodes / agent_path.

    Args:
        credential_error: The ``CredentialError`` raised by validation.
        nodes: Graph nodes (preferred — avoids re-loading from disk).
        agent_path: Agent directory path (used when nodes aren't available).
    """
    from framework.credentials.setup import CredentialSetupSession

    # Prefer the validation result attached to the exception
    result: CredentialValidationResult | None = getattr(credential_error, "validation_result", None)
    if result is not None:
        missing = [_status_to_missing(c) for c in result.failed]
        return CredentialSetupSession(missing)

    # Fallback: re-detect from nodes or agent_path
    if nodes is not None:
        return CredentialSetupSession.from_nodes(nodes)
    elif agent_path is not None:
        return CredentialSetupSession.from_agent_path(agent_path)
    return CredentialSetupSession(missing=[])


def _status_to_missing(c: CredentialStatus):
    """Convert a CredentialStatus to a MissingCredential for the setup flow."""
    from framework.credentials.setup import MissingCredential

    return MissingCredential(
        credential_name=c.credential_name,
        env_var=c.env_var,
        description=c.description,
        help_url=c.help_url,
        api_key_instructions=c.api_key_instructions,
        tools=c.tools,
        node_types=c.node_types,
        aden_supported=c.aden_supported,
        direct_api_key_supported=c.direct_api_key_supported,
        credential_id=c.credential_id,
        credential_key=c.credential_key,
    )
