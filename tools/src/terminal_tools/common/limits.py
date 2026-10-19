"""Shell resolution + resource limits.

The single place that decides which shell binary we invoke and how to
strip zsh-specific environment leakage. Per the terminal-tools security
stance (see ``destructive_warning.py`` neighbours), zsh constructs
(``zmodload``, ``=cmd``, ``zpty``, ``ztcp``) bypass bash-shaped
checks — refusing zsh isn't aesthetic, it's a deliberate hardening
choice.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# `resource` is POSIX-only. On Windows it's absent; setrlimit-based limits
# don't apply, and make_preexec_fn() returns None unconditionally below.
if os.name == "nt":
    resource = None  # type: ignore[assignment]
else:
    import resource  # type: ignore[no-redef]

# Env vars that influence zsh startup. Strip these before exec so a
# user with zsh dotfiles can't accidentally jam zsh behaviour into
# the bash subprocess.
_ZSH_ENV_PREFIXES: tuple[str, ...] = ("ZDOTDIR", "ZSH_")


class ZshRefused(ValueError):
    """Raised when an explicit zsh shell is requested."""


@dataclass(frozen=True)
class ShellSpec:
    """How to invoke a resolved shell.

    ``executable`` is the shell binary (or ``None`` for direct-exec, when
    ``shell=False`` and the platform has a useful direct path). ``argv_prefix``
    are the flags between the executable and the command string —
    ``("-c",)`` for bash, ``("-NoProfile", "-NonInteractive", "-Command")``
    for PowerShell, ``("/c",)`` for cmd. ``kind`` is the dialect the agent
    sees in the envelope's ``shell_kind`` field so it can adapt syntax:
    ``"bash" | "powershell" | "cmd" | "direct"``.
    """

    executable: str | None
    argv_prefix: tuple[str, ...]
    kind: str

    def build_argv(self, command: str) -> list[str]:
        if self.executable is None:
            return [command]
        return [self.executable, *self.argv_prefix, command]


_DIRECT_SPEC = ShellSpec(None, (), "direct")

# Git for Windows default install locations, probed BEFORE PATH so we don't
# accidentally pick C:\Windows\System32\bash.exe — that's the WSL launcher,
# which drops into a Linux distro with a different filesystem view, not the
# Git Bash userland the tool surface expects.
_WINDOWS_BASH_FIXED = (
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files\Git\usr\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
)


def _windows_bash() -> str | None:
    """Locate a real Git Bash on Windows, or None.

    Priority: ``HIVE_BASH_PATH`` override → known Git-for-Windows install
    dirs → PATH (excluding WSL's ``System32\\bash.exe``).
    """
    env_bash = os.environ.get("HIVE_BASH_PATH")
    if env_bash and os.path.isfile(env_bash):
        return env_bash

    candidates = list(_WINDOWS_BASH_FIXED)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(os.path.join(local, "Programs", "Git", "bin", "bash.exe"))
    pf = os.environ.get("ProgramW6432")
    if pf:
        candidates.append(os.path.join(pf, "Git", "bin", "bash.exe"))
    for cand in candidates:
        if os.path.isfile(cand):
            return cand

    found = shutil.which("bash")
    if found and "system32" not in found.replace("/", "\\").lower():
        return found
    return None


def _windows_powershell() -> str | None:
    """Locate PowerShell on Windows.

    Prefers ``pwsh`` (7+, supports ``&&`` / ``||``) then Windows PowerShell
    5.1, which ships on every host (resolved by absolute path so a stripped
    PATH can't hide it).
    """
    for name in ("pwsh", "powershell"):
        found = shutil.which(name)
        if found:
            return found
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    fallback = os.path.join(sysroot, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return fallback if os.path.isfile(fallback) else None


def _windows_cmd() -> str | None:
    """Locate cmd.exe — the guaranteed floor on Windows."""
    comspec = os.environ.get("ComSpec")
    if comspec and os.path.isfile(comspec):
        return comspec
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    fallback = os.path.join(sysroot, "System32", "cmd.exe")
    if os.path.isfile(fallback):
        return fallback
    return shutil.which("cmd")


def _kind_for_path(path: str) -> tuple[str, tuple[str, ...]]:
    """Derive ``(kind, argv_prefix)`` from an explicit shell path."""
    # Split on both separators so a Windows path (backslash) classifies
    # correctly even on a POSIX host — os.path.basename only splits on "/".
    base = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if "pwsh" in base or "powershell" in base:
        return "powershell", ("-NoProfile", "-NonInteractive", "-Command")
    if base in ("cmd", "cmd.exe"):
        return "cmd", ("/c",)
    # bash / sh / dash / busybox / anything else POSIX-shaped.
    return "bash", ("-c",)


def _windows_shell_spec() -> ShellSpec:
    """Resolve the Windows shell in priority order: Git Bash → PowerShell → cmd.

    Git Bash keeps the whole bash-shaped tool surface (coreutils, the
    command_guard kill patterns, find/grep/sed idioms) working. PowerShell is
    the always-present fallback; cmd is the floor. The chosen dialect is
    surfaced to the agent via ``shell_kind`` so it can adapt syntax when bash
    isn't available.
    """
    bash = _windows_bash()
    if bash:
        return ShellSpec(bash, ("-c",), "bash")
    ps = _windows_powershell()
    if ps:
        return ShellSpec(ps, ("-NoProfile", "-NonInteractive", "-Command"), "powershell")
    cmd = _windows_cmd()
    if cmd:
        return ShellSpec(cmd, ("/c",), "cmd")
    # Nothing resolved (essentially impossible — cmd.exe is always present).
    return _DIRECT_SPEC


def resolve_shell_spec(shell: bool | str) -> ShellSpec:
    """Resolve how to invoke ``shell`` into a :class:`ShellSpec`.

    - ``shell=False``/``None`` → direct-exec (``executable=None``)
    - ``shell=True`` → POSIX: ``/bin/bash``; Windows: Git Bash → PowerShell → cmd
    - ``shell="/path/to/sh"`` → that path, dialect inferred from its basename
    - any zsh-containing path → raises :class:`ZshRefused`
    """
    if shell is False or shell is None:
        return _DIRECT_SPEC

    if shell is True:
        if os.name == "nt":
            return _windows_shell_spec()
        return ShellSpec("/bin/bash", ("-c",), "bash")

    if not isinstance(shell, str):
        raise TypeError(f"shell must be bool or str, got {type(shell).__name__}")

    lower = shell.lower()
    if "zsh" in lower:
        raise ZshRefused(
            f"shell={shell!r} rejected: terminal-tools is bash-only on POSIX. "
            "Use shell=True (bash) or omit the shell parameter to exec directly. "
            "This is a deliberate security stance — zsh has command/builtin "
            "classes (zmodload, =cmd, zpty, ztcp) that bypass bash-shaped checks."
        )

    kind, prefix = _kind_for_path(shell)
    return ShellSpec(shell, prefix, kind)


def _resolve_shell(shell: bool | str) -> str | None:
    """Back-compat shim: return just the shell executable (or None).

    Retained for the PTY session path (POSIX-only) and callers that only need
    the binary. New code wanting the invocation flags + dialect should call
    :func:`resolve_shell_spec`.
    """
    return resolve_shell_spec(shell).executable


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
_LIMIT_MAP: dict[str, tuple[int, int]] = (
    {
        "cpu_sec": (resource.RLIMIT_CPU, 1),
        "rss_mb": (resource.RLIMIT_AS, 1024 * 1024),
        "fsize_mb": (resource.RLIMIT_FSIZE, 1024 * 1024),
        "nofile": (resource.RLIMIT_NOFILE, 1),
    }
    if resource is not None
    else {}
)


def make_preexec_fn(limits: dict[str, int] | None) -> Callable[[], None] | None:
    """Build a preexec_fn that applies setrlimit before exec.

    Returns None if no limits are configured (so subprocess.Popen can
    skip the fork hook entirely). Unknown keys are ignored — agents
    pass arbitrary dicts and we don't want a typo to crash exec.
    """
    if not limits:
        return None
    if resource is None:
        # Windows: subprocess.Popen rejects preexec_fn, and we can't apply
        # POSIX setrlimit here anyway. Skip enforcement silently.
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
    "ShellSpec",
    "ZshRefused",
    "_resolve_shell",
    "coerce_limits",
    "make_preexec_fn",
    "resolve_shell_spec",
    "sanitized_env",
]
