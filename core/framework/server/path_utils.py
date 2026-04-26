"""Shared path validation utilities."""

from pathlib import Path
from aiohttp import web

# Anchor to the repository root so allowed roots are independent of CWD.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

_ALLOWED_AGENT_ROOTS: tuple[Path, ...] | None = None


def _get_allowed_agent_roots() -> tuple[Path, ...]:
    """Return resolved allowed root directories for agent loading.

    Roots are anchored to the repository root (derived from ``__file__``)
    so the allowlist is correct regardless of the process's working
    directory.
    """
    global _ALLOWED_AGENT_ROOTS
    if _ALLOWED_AGENT_ROOTS is None:
        _ALLOWED_AGENT_ROOTS = (
            (_REPO_ROOT / "exports").resolve(),
            (_REPO_ROOT / "examples").resolve(),
            (Path.home() / ".hive" / "agents").resolve(),
        )
    return _ALLOWED_AGENT_ROOTS


def validate_agent_path(agent_path: str | Path) -> Path:
    """Validate that an agent path resolves inside an allowed directory.

    Prevents arbitrary code execution via ``importlib.import_module`` by
    restricting agent loading to known safe directories: ``exports/``,
    ``examples/``, and ``~/.hive/agents/``.

    Returns the resolved ``Path`` on success.

    Raises:
        ValueError: If the path is outside all allowed roots.
    """
    resolved = Path(agent_path).expanduser().resolve()
    for root in _get_allowed_agent_roots():
        if resolved.is_relative_to(root) and resolved != root:
            return resolved
    raise ValueError(
        "agent_path must be inside an allowed directory (exports/, examples/, or ~/.hive/agents/)"
    )


def safe_path_segment(value: str) -> str:
    """Validate a URL path parameter is a safe filesystem name.

    Raises HTTPBadRequest if the value contains path separators,
    traversal sequences, control characters, or other pathological inputs.
    """
    if (
        not value
        or value in (".", "..")
        or len(value) > 255
        or "/" in value
        or "\\" in value
        or "\x00" in value
        or value.strip() != value
        or any(ord(c) < 0x20 for c in value)
    ):
        raise web.HTTPBadRequest(reason="Invalid path parameter")
    return value
