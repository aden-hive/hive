"""Smoke test: load the server module, register tools, assert all 10 land."""

from __future__ import annotations

EXPECTED_TOOLS = {
    "terminal_exec",
    "terminal_job_start",
    "terminal_job_logs",
    "terminal_job_manage",
    "terminal_pty_open",
    "terminal_pty_run",
    "terminal_pty_close",
    "terminal_rg",
    "terminal_find",
    "terminal_output_get",
}


def test_register_terminal_tools_lands_all_ten(mcp):
    from terminal_tools import register_terminal_tools

    names = register_terminal_tools(mcp)
    assert set(names) == EXPECTED_TOOLS, f"missing: {EXPECTED_TOOLS - set(names)}, extra: {set(names) - EXPECTED_TOOLS}"


def test_all_tools_have_terminal_prefix(mcp):
    from terminal_tools import register_terminal_tools

    names = register_terminal_tools(mcp)
    for n in names:
        assert n.startswith("terminal_"), f"tool {n!r} missing terminal_ prefix"
