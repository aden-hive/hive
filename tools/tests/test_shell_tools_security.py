"""Security/policy tests: zsh refusal, env stripping, destructive catalog."""

from __future__ import annotations

import pytest


def test_resolve_shell_rejects_zsh():
    from shell_tools.common.limits import ZshRefused, _resolve_shell

    for path in ("/bin/zsh", "/usr/bin/zsh", "/usr/local/bin/zsh", "ZSH"):
        with pytest.raises(ZshRefused):
            _resolve_shell(path)


def test_resolve_shell_accepts_bash():
    from shell_tools.common.limits import _resolve_shell

    assert _resolve_shell(True) == "/bin/bash"
    assert _resolve_shell("/bin/bash") == "/bin/bash"
    assert _resolve_shell(False) is None


def test_sanitized_env_strips_zsh_vars(monkeypatch):
    from shell_tools.common.limits import sanitized_env

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
    from shell_tools.common.destructive_warning import get_warning

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
    from shell_tools.common.destructive_warning import get_warning

    for cmd in ["ls -la", "echo hi", "git status", "git commit -m 'x'"]:
        assert get_warning(cmd) is None, f"unexpected warning for {cmd!r}"


def test_semantic_exit_grep():
    from shell_tools.common.semantic_exit import classify

    status, msg = classify("grep foo /tmp/x", 0)
    assert status == "ok"
    status, msg = classify("grep foo /tmp/x", 1)
    assert status == "ok"
    assert "No matches" in msg
    status, msg = classify("grep foo /tmp/x", 2)
    assert status == "error"


def test_semantic_exit_default():
    from shell_tools.common.semantic_exit import classify

    status, msg = classify("ls", 0)
    assert status == "ok"
    assert msg is None
    status, msg = classify("ls", 1)
    assert status == "error"


def test_semantic_exit_signaled():
    from shell_tools.common.semantic_exit import classify

    status, msg = classify("sleep 999", -15, signaled=True)
    assert status == "signal"


def test_semantic_exit_timed_out():
    from shell_tools.common.semantic_exit import classify

    status, msg = classify("sleep 999", None, timed_out=True)
    assert status == "error"
    assert "timed out" in msg.lower()
