"""Smoke test: load the server module, register tools, assert all 10 land."""

from __future__ import annotations

EXPECTED_TOOLS = {
    "shell_exec",
    "shell_job_start",
    "shell_job_logs",
    "shell_job_manage",
    "shell_pty_open",
    "shell_pty_run",
    "shell_pty_close",
    "shell_rg",
    "shell_find",
    "shell_output_get",
}


def test_register_shell_tools_lands_all_ten(mcp):
    from shell_tools import register_shell_tools

    names = register_shell_tools(mcp)
    assert set(names) == EXPECTED_TOOLS, (
        f"missing: {EXPECTED_TOOLS - set(names)}, extra: {set(names) - EXPECTED_TOOLS}"
    )


def test_all_tools_have_shell_prefix(mcp):
    from shell_tools import register_shell_tools

    names = register_shell_tools(mcp)
    for n in names:
        assert n.startswith("shell_"), f"tool {n!r} missing shell_ prefix"
