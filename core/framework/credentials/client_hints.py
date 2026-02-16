"""Client-aware UX hints for credential setup guidance.

The framework should stay provider-agnostic by default. This module returns
generic guidance unless a client is explicitly known.
"""

from __future__ import annotations

import os
from typing import Literal

ClientType = Literal["claude", "codex", "cursor", "generic"]

_CLIENT_ALIASES = {
    "claude": "claude",
    "claude_code": "claude",
    "claude-code": "claude",
    "codex": "codex",
    "cursor": "cursor",
    "generic": "generic",
}


def detect_client_environment() -> ClientType:
    """Detect the active coding client, defaulting to generic."""
    override = os.environ.get("HIVE_CLIENT", "").strip().lower()
    if override in _CLIENT_ALIASES:
        return _CLIENT_ALIASES[override]

    # Explicit client env markers take precedence over heuristics.
    if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE"):
        return "claude"
    if os.environ.get("CODEX_HOME") or os.environ.get("CODEX_SANDBOX"):
        return "codex"
    if os.environ.get("CURSOR_TRACE_ID") or os.environ.get("CURSOR_AGENT"):
        return "cursor"

    return "generic"


def get_credential_fix_guidance_lines() -> list[str]:
    """Return user-facing guidance for missing credentials."""
    client = detect_client_environment()
    lines = [
        (
            "To fix: set the missing environment variables above, "
            "or configure credentials in Hive's encrypted store (~/.hive/credentials)."
        )
    ]

    if client in {"claude", "codex", "cursor"}:
        lines.append(
            "If your coding client supports Hive skills, run: /hive-credentials."
        )

    lines.append(
        "If you've already set up credentials, restart your terminal or reload your shell profile."
    )
    return lines

