"""Client-aware UX hints for credential setup guidance.

The framework should stay provider-agnostic by default. This module returns
generic guidance unless a client is explicitly known.
"""

from __future__ import annotations

import os
from typing import Literal

ClientType = Literal["claude", "codex", "cursor", "antigravity", "generic"]

_CLIENT_ALIASES = {
    "claude": "claude",
    "claude_code": "claude",
    "claude-code": "claude",
    "codex": "codex",
    "cursor": "cursor",
    "antigravity": "antigravity",
    "antigravity-ide": "antigravity",
    "gemini": "antigravity",
    "generic": "generic",
}


def detect_client_environment() -> ClientType:
    """Detect the active coding client from HIVE_CLIENT, defaulting to generic."""
    override = os.environ.get("HIVE_CLIENT", "").strip().lower()
    if override in _CLIENT_ALIASES:
        return _CLIENT_ALIASES[override]

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

    if client in {"claude", "codex", "cursor", "antigravity"}:
        lines.append(
            "If your coding client supports Hive skills, run: /hive-credentials."
        )

    lines.append(
        "If you've already set up credentials, restart your terminal or reload your shell profile."
    )
    return lines
