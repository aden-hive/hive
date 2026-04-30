"""Shell resolution + resource limits.

The single place that decides which shell binary we invoke and how to
strip zsh-specific environment leakage. Per the shell-tools security
stance (see ``destructive_warning.py`` neighbours), zsh constructs
(``zmodload``, ``=cmd``, ``zpty``, ``ztcp``) bypass bash-shaped
checks — refusing zsh isn't aesthetic, it's a deliberate hardening
choice.
"""

from __future__ import annotations

import os
import resource
from collections.abc import Callable
from typing import Any

# Env vars that influence zsh startup. Strip these before exec so a
# user with zsh dotfiles can't accidentally jam zsh behaviour into
# the bash subprocess.
_ZSH_ENV_PREFIXES: tuple[str, ...] = ("ZDOTDIR", "ZSH_")


class ZshRefused(ValueError):
    """Raised when an explicit zsh shell is requested."""


def _resolve_shell(shell: bool | str) -> str | None:
    """Return the shell executable to use, or None for direct exec.

    - ``shell=False`` → None (caller should exec command directly)
    - ``shell=True`` → ``/bin/bash`` always (ignores ``$SHELL``)
    - ``shell="/bin/bash"`` or any path containing ``bash`` → that path
    - ``shell="/bin/zsh"`` or any zsh-containing path → raises ZshRefused

    Caller is expected to invoke as ``[shell_path, "-c", command]``.
    """
    if shell is False or shell is None:
        return None

    if shell is True:
        return "/bin/bash"

    if not isinstance(shell, str):
        raise TypeError(f"shell must be bool or str, got {type(shell).__name__}")

    lower = shell.lower()
    if "zsh" in lower:
        raise ZshRefused(
            f"shell={shell!r} rejected: shell-tools is bash-only on POSIX. "
            "Use shell=True (bash) or omit the shell parameter to exec directly. "
            "This is a deliberate security stance — zsh has command/builtin "
            "classes (zmodload, =cmd, zpty, ztcp) that bypass bash-shaped checks."
        )

    return shell


def sanitized_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Return os.environ with zsh-related vars stripped, plus optional overrides.

    Stripping ``ZDOTDIR`` and ``ZSH_*`` ensures zsh dotfiles don't leak
    into the bash subprocess's startup. Bash dotfiles still apply when
    the shell is invoked interactively.
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith(_ZSH_ENV_PREFIXES)}
    if extra:
        env.update(extra)
    return env


# ── Resource limits ───────────────────────────────────────────────────


# Maps the public limit name to its (resource constant, multiplier)
# tuple. Multipliers convert the agent-friendly unit (seconds, MB) to
# the kernel unit (seconds, bytes).
_LIMIT_MAP: dict[str, tuple[int, int]] = {
    "cpu_sec": (resource.RLIMIT_CPU, 1),
    "rss_mb": (resource.RLIMIT_AS, 1024 * 1024),
    "fsize_mb": (resource.RLIMIT_FSIZE, 1024 * 1024),
    "nofile": (resource.RLIMIT_NOFILE, 1),
}


def make_preexec_fn(limits: dict[str, int] | None) -> Callable[[], None] | None:
    """Build a preexec_fn that applies setrlimit before exec.

    Returns None if no limits are configured (so subprocess.Popen can
    skip the fork hook entirely). Unknown keys are ignored — agents
    pass arbitrary dicts and we don't want a typo to crash exec.
    """
    if not limits:
        return None

    def _apply() -> None:
        for key, value in limits.items():
            spec = _LIMIT_MAP.get(key)
            if spec is None or value is None:
                continue
            rlimit_const, multiplier = spec
            limit = int(value) * multiplier
            try:
                resource.setrlimit(rlimit_const, (limit, limit))
            except (OSError, ValueError):
                # Hard limit may exceed the current ceiling. Best-effort:
                # set just the soft limit to whatever we can.
                try:
                    soft, hard = resource.getrlimit(rlimit_const)
                    resource.setrlimit(rlimit_const, (min(limit, hard), hard))
                except Exception:
                    pass

    return _apply


def coerce_limits(limits: Any) -> dict[str, int] | None:
    """Validate and normalize a user-supplied limits dict.

    Accepts the four supported keys (``cpu_sec``, ``rss_mb``,
    ``fsize_mb``, ``nofile``); silently drops unknown keys; returns
    None when the result is empty. Negative or non-int values are
    dropped too — invalid limits are better as no-ops than as errors,
    since the agent didn't ask for enforcement of a *specific*
    failure mode.
    """
    if not limits:
        return None
    if not isinstance(limits, dict):
        return None

    out: dict[str, int] = {}
    for key in _LIMIT_MAP:
        value = limits.get(key)
        if value is None:
            continue
        try:
            ivalue = int(value)
        except (TypeError, ValueError):
            continue
        if ivalue <= 0:
            continue
        out[key] = ivalue
    return out or None


__all__ = [
    "ZshRefused",
    "_resolve_shell",
    "coerce_limits",
    "make_preexec_fn",
    "sanitized_env",
]
