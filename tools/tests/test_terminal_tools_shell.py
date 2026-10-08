"""Cross-platform shell resolution: ShellSpec / resolve_shell_spec.

These exercise the Windows branch (Git Bash → PowerShell → cmd) on any host
by monkeypatching os.name + the per-shell locators, so the full matrix is
covered on the POSIX CI without a Windows box.
"""

from __future__ import annotations

import pytest

from terminal_tools.common import limits
from terminal_tools.common.limits import (
    ZshRefused,
    _resolve_shell,
    resolve_shell_spec,
)


def _force_windows(monkeypatch):
    monkeypatch.setattr(limits.os, "name", "nt")


# ── POSIX behavior is unchanged ──────────────────────────────────────────


def test_posix_shell_true_is_bash(monkeypatch):
    monkeypatch.setattr(limits.os, "name", "posix")
    spec = resolve_shell_spec(True)
    assert spec.executable == "/bin/bash"
    assert spec.argv_prefix == ("-c",)
    assert spec.kind == "bash"
    assert spec.build_argv("echo hi") == ["/bin/bash", "-c", "echo hi"]


def test_shell_false_is_direct():
    spec = resolve_shell_spec(False)
    assert spec.executable is None
    assert spec.kind == "direct"
    assert spec.build_argv("echo hi") == ["echo hi"]


def test_explicit_bash_path():
    spec = resolve_shell_spec("/usr/bin/bash")
    assert spec.executable == "/usr/bin/bash"
    assert spec.kind == "bash"
    assert spec.argv_prefix == ("-c",)


def test_zsh_rejected():
    for path in ("/bin/zsh", "/usr/local/bin/zsh", "ZSH"):
        with pytest.raises(ZshRefused):
            resolve_shell_spec(path)


def test_resolve_shell_backcompat(monkeypatch):
    monkeypatch.setattr(limits.os, "name", "posix")
    assert _resolve_shell(True) == "/bin/bash"
    assert _resolve_shell("/bin/bash") == "/bin/bash"
    assert _resolve_shell(False) is None


# ── Windows priority: Git Bash → PowerShell → cmd ────────────────────────


def test_windows_prefers_git_bash(monkeypatch):
    _force_windows(monkeypatch)
    monkeypatch.setattr(limits, "_windows_bash", lambda: r"C:\Program Files\Git\bin\bash.exe")
    monkeypatch.setattr(limits, "_windows_powershell", lambda: r"C:\ps.exe")
    monkeypatch.setattr(limits, "_windows_cmd", lambda: r"C:\cmd.exe")
    spec = resolve_shell_spec(True)
    assert spec.kind == "bash"
    assert spec.executable.endswith("bash.exe")
    assert spec.argv_prefix == ("-c",)


def test_windows_falls_back_to_powershell(monkeypatch):
    _force_windows(monkeypatch)
    monkeypatch.setattr(limits, "_windows_bash", lambda: None)
    monkeypatch.setattr(
        limits,
        "_windows_powershell",
        lambda: r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
    )
    monkeypatch.setattr(limits, "_windows_cmd", lambda: r"C:\Windows\System32\cmd.exe")
    spec = resolve_shell_spec(True)
    assert spec.kind == "powershell"
    assert spec.argv_prefix == ("-NoProfile", "-NonInteractive", "-Command")
    assert spec.build_argv("Get-ChildItem")[1:] == [
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "Get-ChildItem",
    ]


def test_windows_falls_back_to_cmd(monkeypatch):
    _force_windows(monkeypatch)
    monkeypatch.setattr(limits, "_windows_bash", lambda: None)
    monkeypatch.setattr(limits, "_windows_powershell", lambda: None)
    monkeypatch.setattr(limits, "_windows_cmd", lambda: r"C:\Windows\System32\cmd.exe")
    spec = resolve_shell_spec(True)
    assert spec.kind == "cmd"
    assert spec.argv_prefix == ("/c",)
    assert spec.build_argv("dir") == [r"C:\Windows\System32\cmd.exe", "/c", "dir"]


# ── Explicit Windows shell paths map to the right dialect ─────────────────


@pytest.mark.parametrize(
    "path,kind,prefix",
    [
        (r"C:\Program Files\Git\bin\bash.exe", "bash", ("-c",)),
        (
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
            "powershell",
            ("-NoProfile", "-NonInteractive", "-Command"),
        ),
        (
            r"C:\Program Files\PowerShell\7\pwsh.exe",
            "powershell",
            ("-NoProfile", "-NonInteractive", "-Command"),
        ),
        (r"C:\Windows\System32\cmd.exe", "cmd", ("/c",)),
    ],
)
def test_kind_for_explicit_path(path, kind, prefix):
    spec = resolve_shell_spec(path)
    assert spec.kind == kind
    assert spec.argv_prefix == prefix
    assert spec.executable == path


# ── _windows_bash excludes the WSL System32 launcher ─────────────────────


def test_windows_bash_rejects_wsl_launcher(monkeypatch):
    monkeypatch.delenv("HIVE_BASH_PATH", raising=False)
    # No Git install dirs present, and PATH only has WSL's System32 launcher.
    monkeypatch.setattr(limits.os.path, "isfile", lambda p: False)
    monkeypatch.setattr(limits.shutil, "which", lambda name: r"C:\Windows\System32\bash.exe")
    assert limits._windows_bash() is None


def test_windows_bash_accepts_real_path_bash(monkeypatch):
    monkeypatch.delenv("HIVE_BASH_PATH", raising=False)
    monkeypatch.setattr(limits.os.path, "isfile", lambda p: False)
    monkeypatch.setattr(limits.shutil, "which", lambda name: r"C:\tools\git\bin\bash.exe")
    assert limits._windows_bash() == r"C:\tools\git\bin\bash.exe"


def test_windows_bash_env_override(monkeypatch):
    monkeypatch.setenv("HIVE_BASH_PATH", r"D:\custom\bash.exe")
    monkeypatch.setattr(limits.os.path, "isfile", lambda p: p == r"D:\custom\bash.exe")
    assert limits._windows_bash() == r"D:\custom\bash.exe"
