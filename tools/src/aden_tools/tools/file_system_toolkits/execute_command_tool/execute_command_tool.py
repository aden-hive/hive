"""Shell command execution tool.

Three tools are registered:

* ``execute_command_tool`` runs a command synchronously with a per-call
  timeout (default 120s, max 600s). Uses ``asyncio.create_subprocess_shell``
  so the MCP event loop is not blocked while the child runs.
* ``bash_output`` polls a background job started with
  ``execute_command_tool(run_in_background=True)`` and returns any new
  stdout/stderr since the last poll plus the current status.
* ``bash_kill`` terminates a background job (SIGTERM then SIGKILL after
  a 3-second grace period).

All three go through the same pre-execution safety blocklist in
``command_sanitizer.py``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from mcp.server.fastmcp import FastMCP

from ..command_sanitizer import CommandBlockedError, validate_command
from ..security import AGENT_SANDBOXES_DIR, get_sandboxed_path
from .background_jobs import get as get_job, kill as kill_job, spawn as spawn_job

# Structured execution logger. Every command that actually runs (foreground
# or background) is recorded here with agent_id, command preview, and outcome.
# Pairs with aden.security for a complete audit trail: security logs what was
# blocked; execution logs what ran.
_exec_logger = logging.getLogger("aden.execution")

# Bounds on per-call timeout. 1s minimum prevents accidental zeros that
# would cause every command to fail. 600s maximum (10 min) is the same
# ceiling Claude Code uses for its Bash tool; builds and test suites
# longer than that should use run_in_background instead.
_MIN_TIMEOUT = 1
_MAX_TIMEOUT = 600
_DEFAULT_TIMEOUT = 120


def _resolve_cwd(cwd: str | None, agent_id: str) -> str:
    agent_root = os.path.join(AGENT_SANDBOXES_DIR, agent_id, "current")
    os.makedirs(agent_root, exist_ok=True)
    if cwd:
        return get_sandboxed_path(cwd, agent_id)
    return agent_root


def register_tools(mcp: FastMCP) -> None:
    """Register command execution tools with the MCP server."""

    @mcp.tool()
    async def execute_command_tool(
        command: str,
        agent_id: str,
        cwd: str | None = None,
        timeout_seconds: int = _DEFAULT_TIMEOUT,
        run_in_background: bool = False,
    ) -> dict:
        """
        Purpose
            Execute a shell command within the agent sandbox.

        When to use
            Run validators, linters, builds, test suites
            Generate derived artifacts (indexes, summaries)
            Perform controlled maintenance tasks
            Start long-running processes via ``run_in_background=True``
            (dev servers, watchers, file-triggered builds)

        Rules & Constraints
            No network access unless explicitly allowed
            No destructive commands (rm -rf, system modification)
            Commands are validated against a safety blocklist before
            execution. The blocklist catches dangerous executables,
            destructive flag combos, and injection patterns in chained
            commands (cmd1 && cmd2, cmd1 | cmd2). All blocked commands
            and all executions are recorded in structured audit logs
            (aden.security / aden.execution).
            timeout_seconds is clamped to [1, 600]. For longer-running
            work use run_in_background=True + bash_output to poll.

        Args:
            command: The shell command to execute.
            agent_id: The ID of the agent (auto-injected).
            cwd: Working directory for the command (relative to the
                agent sandbox). Defaults to the sandbox root.
            timeout_seconds: Max wall-clock seconds the foreground
                command is allowed to run. Ignored when
                run_in_background=True. Default 120, max 600.
            run_in_background: If True, spawn the command and return
                immediately with a job id. Use bash_output(id=...) to
                read output and bash_kill(id=...) to stop it.

        Returns:
            For foreground commands: dict with stdout, stderr, return_code,
            elapsed_seconds.
            For background commands: dict with id, pid, started_at, and
            instructions for polling / killing the job.
            On error: dict with an "error" key.
        """
        try:
            validate_command(command)
        except CommandBlockedError as e:
            return {"error": f"Command blocked: {e}", "blocked": True}

        try:
            secure_cwd = _resolve_cwd(cwd, agent_id)
        except Exception as e:
            return {"error": f"Failed to resolve cwd: {e}"}

        if run_in_background:
            try:
                job = await spawn_job(command, secure_cwd, agent_id)
            except Exception as e:
                return {"error": f"Failed to spawn background job: {e}"}
            _exec_logger.info(
                "command_spawned",
                extra={
                    "agent_id": agent_id,
                    "background": True,
                    "job_id": job.id,
                    "cwd": secure_cwd,
                    "command_preview": command[:120],
                },
            )
            return {
                "success": True,
                "background": True,
                "id": job.id,
                "pid": job.process.pid,
                "command": command,
                "cwd": cwd or ".",
                "started_at": job.started_at,
                "hint": (
                    "Background job started. Call "
                    f"bash_output(id='{job.id}') to read output, or "
                    f"bash_kill(id='{job.id}') to terminate it."
                ),
            }

        # Foreground path: clamp timeout, spawn, wait with a watchdog.
        try:
            timeout = max(_MIN_TIMEOUT, min(_MAX_TIMEOUT, int(timeout_seconds)))
        except (TypeError, ValueError):
            timeout = _DEFAULT_TIMEOUT

        started = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=secure_cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            return {"error": f"Failed to execute command: {e}"}

        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            elapsed = round(time.monotonic() - started, 2)
            _exec_logger.info(
                "command_executed",
                extra={
                    "agent_id": agent_id,
                    "command_preview": command.strip()[:120],
                    "cwd": secure_cwd,
                    "background": False,
                    "return_code": -1,  # -1 represents timeout/killed
                    "elapsed_seconds": elapsed,
                    "error": "TimeoutError",
                },
            )
            # Child is still running: kill it, drain what it already
            # wrote so the agent gets a partial log, then report.
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=2.0)
            except (TimeoutError, Exception):
                stdout_b, stderr_b = b"", b""
            return {
                "error": (
                    f"Command timed out after {timeout} seconds. "
                    f"For longer work pass timeout_seconds (max 600) or "
                    f"run_in_background=True."
                ),
                "timed_out": True,
                "elapsed_seconds": elapsed,
                "stdout": stdout_b.decode("utf-8", errors="replace"),
                "stderr": stderr_b.decode("utf-8", errors="replace"),
            }
        except Exception as e:
            return {"error": f"Failed while running command: {e}"}

        elapsed = round(time.monotonic() - started, 2)
        _exec_logger.info(
            "command_executed",
            extra={
                "agent_id": agent_id,
                "background": False,
                "return_code": proc.returncode,
                "elapsed_seconds": elapsed,
                "cwd": secure_cwd,
                # Note: python -c '...' one-liners are intentionally allowed
                # to preserve developer utility. The full command is captured
                # here so all one-liner executions are visible in the audit
                # trail even when their content cannot be pre-validated.
                "command_preview": command[:120],
            },
        )
        return {
            "success": True,
            "command": command,
            "return_code": proc.returncode,
            "stdout": stdout_b.decode("utf-8", errors="replace"),
            "stderr": stderr_b.decode("utf-8", errors="replace"),
            "cwd": cwd or ".",
            "elapsed_seconds": elapsed,
        }

    @mcp.tool()
    async def bash_output(id: str, agent_id: str) -> dict:
        """Poll a background command for new output and its current status.

        Returns any stdout/stderr bytes written since the last call.
        The status is one of "running", "exited(N)", or "killed".
        When the job has finished and all output has been consumed, it
        is removed from the registry on the next poll.

        Args:
            id: The job id returned from
                execute_command_tool(run_in_background=True).
            agent_id: The ID of the agent (auto-injected).
        """
        job = await get_job(agent_id, id)
        if job is None:
            return {"error": f"no background job with id '{id}'"}
        new_stdout = job.stdout_buf.read_new()
        new_stderr = job.stderr_buf.read_new()
        return {
            "id": id,
            "status": job.status(),
            "stdout": new_stdout,
            "stderr": new_stderr,
            "elapsed_seconds": round(time.time() - job.started_at, 2),
        }

    @mcp.tool()
    async def bash_kill(id: str, agent_id: str) -> dict:
        """Terminate a background command.

        Sends SIGTERM, waits up to 3 seconds, then escalates to SIGKILL
        if the process is still alive. The job id is then deregistered.

        Args:
            id: The job id returned from
                execute_command_tool(run_in_background=True).
            agent_id: The ID of the agent (auto-injected).
        """
        status = await kill_job(agent_id, id)
        return {"id": id, "status": status}
