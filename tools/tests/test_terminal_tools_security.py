"""Security/policy tests: zsh refusal, env stripping, destructive catalog."""

from __future__ import annotations

import pytest


def test_resolve_shell_rejects_zsh():
    from terminal_tools.common.limits import ZshRefused, _resolve_shell

    for path in ("/bin/zsh", "/usr/bin/zsh", "/usr/local/bin/zsh", "ZSH"):
        with pytest.raises(ZshRefused):
            _resolve_shell(path)


def test_resolve_shell_accepts_bash():
    import os

    from terminal_tools.common.limits import _resolve_shell

    if os.name == "nt":
        # Windows resolves shell=True to the platform shell (Git Bash if
        # installed, else PowerShell/cmd) — never the POSIX "/bin/bash".
        assert _resolve_shell(True) is not None
    else:
        assert _resolve_shell(True) == "/bin/bash"
    # An explicit shell path is always honored verbatim.
    assert _resolve_shell("/bin/bash") == "/bin/bash"
    assert _resolve_shell(False) is None


def test_sanitized_env_strips_zsh_vars(monkeypatch):
    from terminal_tools.common.limits import sanitized_env

    monkeypatch.setenv("ZDOTDIR", "/some/path")
    monkeypatch.setenv("ZSH_VERSION", "5.9")
    monkeypatch.setenv("ZSH_NAME", "zsh")
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    env = sanitized_env()
    assert "ZDOTDIR" not in env
    assert "ZSH_VERSION" not in env
    assert "ZSH_NAME" not in env
    # Non-zsh vars survive
    assert env["PATH"] == "/usr/bin:/bin"


def test_destructive_warning_catalog():
    from terminal_tools.common.destructive_warning import get_warning

    cases = [
        ("rm -rf /tmp/foo", "force-remove"),
        ("rm -r /tmp/foo", "recursively remove"),
        ("git reset --hard HEAD~1", "discard"),
        ("git push --force origin main", "remote history"),
        ("git push -f origin main", "remote history"),
        ("git commit --amend -m 'x'", "rewrite"),
        ("DROP TABLE users;", "drop or truncate"),
        ("DELETE FROM users;", "delete rows"),
        ("kubectl delete pod foo", "Kubernetes"),
        ("terraform destroy", "Terraform"),
    ]
    for cmd, expected in cases:
        warning = get_warning(cmd)
        assert warning is not None, f"expected warning for {cmd!r}"
        assert expected in warning, f"warning {warning!r} should mention {expected!r}"


def test_destructive_warning_clean_commands():
    from terminal_tools.common.destructive_warning import get_warning

    for cmd in ["ls -la", "echo hi", "git status", "git commit -m 'x'"]:
        assert get_warning(cmd) is None, f"unexpected warning for {cmd!r}"


def test_destructive_warning_rm_double_dash_separator():
    """`rm` short flags stay recognised when a `--` end-of-options separator
    follows them, including the `-fr` ordering."""
    from terminal_tools.common.destructive_warning import get_warning

    cases = [
        ("rm -rf -- /tmp/foo", "recursively force-remove"),
        ("rm -fr -- /tmp/foo", "recursively force-remove"),
        ("rm -r -- /tmp/foo", "recursively remove"),
        ("rm -f -- /tmp/foo", "force-remove"),
    ]
    for cmd, expected in cases:
        warning = get_warning(cmd)
        assert warning is not None, f"expected warning for {cmd!r}"
        assert expected in warning, f"warning {warning!r} should mention {expected!r}"


def test_destructive_warning_windows_delete_catalog():
    """On Windows the resolved shell may be PowerShell/cmd — the catalog must
    cover the native delete verbs, not just POSIX `rm`."""
    from terminal_tools.common.destructive_warning import get_warning

    cases = [
        (r"del /F /S /Q C:\temp", "recursively force-delete"),
        (r"del /S /Q C:\temp", "recursively force-delete"),
        (r"del /s C:\temp\*", "recursively delete"),
        (r"del /F important.txt", "force-delete"),
        (r"erase /Q C:\logs\*", "force-delete"),
        (r"rmdir /S /Q C:\build", "directory tree"),
        (r"rd /s /q C:\build", "directory tree"),
    ]
    for cmd, expected in cases:
        warning = get_warning(cmd)
        assert warning is not None, f"expected warning for {cmd!r}"
        assert expected in warning, f"warning {warning!r} should mention {expected!r}"


def test_destructive_warning_powershell_remove_item():
    from terminal_tools.common.destructive_warning import get_warning

    cases = [
        (r"Remove-Item -Recurse -Force C:\x", "recursively force-delete"),
        (r"Remove-Item -Path C:\x -Recurse", "recursively delete"),
        (r"Remove-Item C:\x -Force", "force-delete"),
        # Pipeline form: the verb is not in command position.
        (r"Get-ChildItem C:\t | Remove-Item -Recurse -Force", "recursively force-delete"),
        # PowerShell accepts abbreviated parameter names.
        (r"remove-item -rec -for C:\x", "recursively force-delete"),
        # An explicitly enabled switch still counts.
        (r"Remove-Item -Recurse:$true C:\x", "recursively delete"),
    ]
    for cmd, expected in cases:
        warning = get_warning(cmd)
        assert warning is not None, f"expected warning for {cmd!r}"
        assert expected in warning, f"warning {warning!r} should mention {expected!r}"


def test_destructive_warning_powershell_disabled_switches():
    """PowerShell binds `-Recurse:$false` as a disabled switch — that call is
    not destructive and must not warn."""
    from terminal_tools.common.destructive_warning import get_warning

    for cmd in [
        r"Remove-Item -Recurse:$false -Force:$false C:\x",
        r"Remove-Item -Recurse:$false C:\x",
        r"Remove-Item -Force:$false C:\x",
        r"Remove-Item -Recurse:$False -Force:$False C:\x",
    ]:
        assert get_warning(cmd) is None, f"unexpected warning for {cmd!r}"


def test_destructive_warning_windows_clean_commands():
    """Benign Windows input must not trip the delete patterns: `del`/`rd` are
    short, word-like tokens, so they only count in command position."""
    from terminal_tools.common.destructive_warning import get_warning

    for cmd in [
        'echo "run del /s /q to clean"',  # quoted prose, not a command
        "model /s",  # 'del' inside a word
        "git delete-branch feature/x",  # 'del' inside a word
        r"dir /s C:\src",  # listing, not deleting
        r"rd C:\emptydir",  # non-recursive rmdir
        "Get-Command Remove-Item",  # no -Recurse / -Force
        "Get-Help Remove-Item -Full",
        "findstr /s TODO *.py",
    ]:
        assert get_warning(cmd) is None, f"unexpected warning for {cmd!r}"


def test_command_guard_blocks_windows_browser_kills():
    """On Windows the resolved shell may be PowerShell/cmd — the guard must
    catch the native kill verbs, not just bash pkill/killall."""
    from terminal_tools.common.command_guard import check_command

    blocked = [
        "Stop-Process -Name chrome",
        "Stop-Process -Name msedge -Force",
        "Get-Process chrome | Stop-Process -Force",
        "Get-Process chrome | Where-Object { $_.CPU -gt 1 } | Stop-Process",
        "taskkill /IM chrome.exe /F",
        "taskkill /F /IM msedge.exe",
        "Stop-Process -Name bridge_host",
    ]
    for cmd in blocked:
        assert check_command(cmd) is not None, f"should block: {cmd!r}"


def test_command_guard_blocks_windows_browser_launch():
    from terminal_tools.common.command_guard import check_command

    for cmd in ["Start-Process chrome", "start chrome", 'Start-Process "chrome.exe"']:
        assert check_command(cmd) is not None, f"should block: {cmd!r}"


def test_command_guard_allows_clean_windows_commands():
    from terminal_tools.common.command_guard import check_command

    for cmd in [
        "Get-Process | Sort-Object CPU -Descending",
        "Get-ChildItem C:\\Users",
        "taskkill /IM mytool.exe",  # not a browser/runtime process
        "Stop-Process -Name myworker",  # not a protected process
        "echo chrome",
        "Start-Process notepad",
    ]:
        assert check_command(cmd) is None, f"should allow: {cmd!r}"


def test_semantic_exit_grep():
    from terminal_tools.common.semantic_exit import classify

    status, msg = classify("grep foo /tmp/x", 0)
    assert status == "ok"
    status, msg = classify("grep foo /tmp/x", 1)
    assert status == "ok"
    assert "No matches" in msg
    status, msg = classify("grep foo /tmp/x", 2)
    assert status == "error"


def test_semantic_exit_default():
    from terminal_tools.common.semantic_exit import classify

    status, msg = classify("ls", 0)
    assert status == "ok"
    assert msg is None
    status, msg = classify("ls", 1)
    assert status == "error"


def test_semantic_exit_signaled():
    from terminal_tools.common.semantic_exit import classify

    status, msg = classify("sleep 999", -15, signaled=True)
    assert status == "signal"


def test_semantic_exit_timed_out():
    from terminal_tools.common.semantic_exit import classify

    status, msg = classify("sleep 999", None, timed_out=True)
    assert status == "error"
    assert "timed out" in msg.lower()
