"""Pre-start validation for agent graphs.

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


class PreStartValidationError(Exception):
    """Raised when pre-start validation fails."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        msg = "Pre-start validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        super().__init__(msg)


@dataclass
class PreStartResult:
    """Result of pre-start validation."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_graph_structure(graph: GraphSpec) -> list[str]:
    """Run graph structural validation (includes GCU subagent-only checks).

    Delegates to GraphSpec.validate() which checks entry/terminal nodes,
    edge references, reachability, fan-out rules, and GCU constraints.
    """
    return graph.validate()


def validate_credentials(
    nodes: list[NodeSpec],
    *,
    interactive: bool = True,
    skip: bool = False,
) -> None:
    """Validate agent credentials.

    Extracted from AgentRunner._validate_credentials(). Raises
    CredentialError on failure (interactive mode attempts recovery first).
    """
    if skip:
        return

    from framework.credentials.validation import validate_agent_credentials

    if not interactive:
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
            raise CredentialError(
                "Credential setup incomplete. "
                "Run again after configuring the required credentials."
            ) from None

        validate_agent_credentials(nodes)


def run_prestart_validation(
    graph: GraphSpec,
    *,
    interactive: bool = True,
    skip_credential_validation: bool = False,
) -> PreStartResult:
    """Run all pre-start validations.

    Order:
    1. Graph structure (includes GCU subagent-only checks) — non-recoverable
    2. Credentials — potentially recoverable via interactive setup

    Raises PreStartValidationError for structural issues.
    Raises CredentialError for credential issues.
    """
    # 1. Structural validation (calls graph.validate() which includes GCU checks)
    graph_errors = validate_graph_structure(graph)
    if graph_errors:
        raise PreStartValidationError(graph_errors)

    # 2. Credential validation
    validate_credentials(
        graph.nodes,
        interactive=interactive,
        skip=skip_credential_validation,
    )

    return PreStartResult(valid=True)
