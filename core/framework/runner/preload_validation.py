"""Pre-load validation for agent graphs.

Runs structural and credential checks before MCP servers are spawned.
Fails fast with actionable error messages.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from framework.graph.edge import GraphSpec
    from framework.graph.node import NodeSpec

logger = logging.getLogger(__name__)


class PreloadValidationError(Exception):
    """Raised when pre-load validation fails."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        msg = "Pre-load validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        super().__init__(msg)


@dataclass
class PreloadResult:
    """Result of pre-load validation."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_graph_structure(graph: GraphSpec) -> list[str]:
    """Run graph structural validation (includes GCU subagent-only checks).

    Delegates to GraphSpec.validate() which checks entry/terminal nodes,
    edge references, reachability, fan-out rules, and GCU constraints.
    Returns only errors (warnings are not blocking).
    """
    result = graph.validate()
    return result["errors"]


def validate_credentials(
    nodes: list[NodeSpec],
    *,
    interactive: bool = True,
    skip: bool = False,
) -> None:
    """Validate agent credentials.

    Calls ``validate_agent_credentials`` which performs two-phase validation:
    1. Presence check (env var, encrypted store, Aden sync)
    2. Health check (lightweight HTTP call to verify the key works)

    On failure raises ``CredentialError`` with ``validation_result`` and
    ``failed_cred_names`` attributes preserved from the upstream check.

    In interactive mode (CLI with TTY), attempts recovery via the
    credential setup flow before re-raising.
    """
    if skip:
        return

    from framework.credentials.validation import validate_agent_credentials

    if not interactive:
        # Non-interactive: let CredentialError propagate with full context.
        # validate_agent_credentials attaches .validation_result and
        # .failed_cred_names to the exception automatically.
        validate_agent_credentials(nodes)
        return

    import sys

    from framework.credentials.models import CredentialError

    try:
        validate_agent_credentials(nodes)
    except CredentialError as e:
        if not sys.stdin.isatty():
            raise

        print(f"\n{e}", file=sys.stderr)

        from framework.credentials.validation import build_setup_session_from_error

        session = build_setup_session_from_error(e, nodes=nodes)
        if not session.missing:
            raise

        result = session.run_interactive()
        if not result.success:
            # Preserve the original validation_result so callers can
            # inspect which credentials are still missing.
            exc = CredentialError(
                "Credential setup incomplete. Run again after configuring the required credentials."
            )
            if hasattr(e, "validation_result"):
                exc.validation_result = e.validation_result  # type: ignore[attr-defined]
            if hasattr(e, "failed_cred_names"):
                exc.failed_cred_names = e.failed_cred_names  # type: ignore[attr-defined]
            raise exc from None

        # Re-validate after successful setup — this will raise if still broken,
        # with fresh validation_result attached to the new exception.
        validate_agent_credentials(nodes)


def credential_errors_to_json(exc: Exception) -> dict:
    """Extract structured credential failure details from a CredentialError.

    Returns a dict suitable for JSON serialization with enough detail for
    the queen to report actionable guidance to the user.  Falls back to
    ``str(exc)`` when rich metadata is not available.
    """
    result = getattr(exc, "validation_result", None)
    if result is None:
        return {
            "error": "credentials_required",
            "message": str(exc),
        }

    failed = result.failed
    missing = []
    for c in failed:
        if c.available:
            status = "invalid"
        elif c.aden_not_connected:
            status = "aden_not_connected"
        else:
            status = "missing"
        entry: dict = {
            "credential": c.credential_name,
            "env_var": c.env_var,
            "status": status,
        }
        if c.tools:
            entry["tools"] = c.tools
        if c.node_types:
            entry["node_types"] = c.node_types
        if c.help_url:
            entry["help_url"] = c.help_url
        if c.validation_message:
            entry["validation_message"] = c.validation_message
        missing.append(entry)

    return {
        "error": "credentials_required",
        "message": str(exc),
        "missing_credentials": missing,
    }


def run_preload_validation(
    graph: GraphSpec,
    *,
    interactive: bool = True,
    skip_credential_validation: bool = False,
) -> PreloadResult:
    """Run all pre-load validations.

    Order:
    1. Graph structure (includes GCU subagent-only checks) — non-recoverable
    2. Credentials — potentially recoverable via interactive setup

    Raises PreloadValidationError for structural issues.
    Raises CredentialError for credential issues.
    """
    # 1. Structural validation (calls graph.validate() which includes GCU checks)
    graph_errors = validate_graph_structure(graph)
    if graph_errors:
        raise PreloadValidationError(graph_errors)

    # 2. Credential validation
    validate_credentials(
        graph.nodes,
        interactive=interactive,
        skip=skip_credential_validation,
    )

    return PreloadResult(valid=True)
