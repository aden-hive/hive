"""``shell_exec`` — foreground exec with auto-promotion to background.

The flagship tool. Most agent terminal interactions go through here:
fast commands (<30s) return inline with the standard envelope; longer
commands silently transition into the JobManager and surface a
``job_id`` so the agent can poll. The "should I background this?"
decision is removed — the answer is always yes-if-needed.

Implementation notes:
  - We spawn the process the same way JobManager does, then wait with
    ``proc.wait(timeout=auto_background_after_sec)``. Inline path
    drains pipes via ``proc.communicate()`` to avoid pipe-fill
    deadlocks.
  - Auto-promotion: when the timeout fires while the process is still
    running, we already have its stdin/stdout/stderr file objects.
    We hand them to JobManager which spawns pump threads to fill ring
    buffers from that point on. The agent sees an envelope with
    ``auto_backgrounded=True, exit_code=None, job_id=<…>`` and
    transitions to ``shell_job_logs``. **There's no early-output loss**
    because the pumps start before we return from the tool call.
  - For pure-foreground use (``auto_background_after_sec=0``), we
    fall back to ``proc.communicate(timeout=timeout_sec)`` which has
    the simpler "kill on overall timeout" semantics.
"""

from __future__ import annotations

import subprocess
import threading
import time
from typing import TYPE_CHECKING

from shell_tools.common.limits import (
    ZshRefused,
    _resolve_shell,
    coerce_limits,
    make_preexec_fn,
    sanitized_env,
)
from shell_tools.common.ring_buffer import RingBuffer
from shell_tools.common.truncation import build_exec_envelope
from shell_tools.jobs.manager import JobLimitExceeded, get_manager

if TYPE_CHECKING:
    from fastmcp import FastMCP


def register_exec_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def shell_exec(
        command: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_sec: int = 60,
        auto_background_after_sec: int = 30,
        shell: bool = False,
        stdin: str | None = None,
        limits: dict[str, int] | None = None,
        max_output_kb: int = 256,
    ) -> dict:
        """Run a shell command and capture its output.

        Past auto_background_after_sec, the call auto-promotes to a background
        job and returns immediately with `auto_backgrounded=True, job_id=...`
        — poll with shell_job_logs(job_id, since_offset=...) to read the rest.
        Set auto_background_after_sec=0 to force pure foreground (kill on
        timeout_sec).

        Bash-only on POSIX. Passing shell="/bin/zsh" raises an error — this is
        a deliberate security stance.

        Args:
            command: The command. With shell=False we naively split on
                whitespace; for pipes / quoting / globs use shell=True.
            cwd: Working directory.
            env: Environment override (merged into a sanitized base — zsh
                dotfile vars are stripped).
            timeout_sec: Hard kill deadline. Past this, the process is
                terminated and `timed_out=True` is returned. Should be ≥
                auto_background_after_sec for the auto-promote path to work.
            auto_background_after_sec: Inline budget. Past this, promote to
                a background job and return. 0 disables auto-promotion.
            shell: True for `/bin/bash -c <command>`. zsh refused.
            stdin: Optional stdin payload (string).
            limits: Optional setrlimit caps. Keys: cpu_sec, rss_mb,
                fsize_mb, nofile.
            max_output_kb: Inline output cap. Overflow stashes to an
                output_handle for retrieval via shell_output_get.

        Returns the standard envelope: see `shell-tools-foundations` skill.
        """
        try:
            argv: list[str] | str
            if shell:
                argv = command
            else:
                argv = command.split()
                if not argv:
                    return _err_envelope(command, "command was empty")

            full_env = sanitized_env(env) if env is not None else None
            preexec = make_preexec_fn(coerce_limits(limits))
        except ZshRefused as e:
            return _err_envelope(command, str(e))

        # Resolve shell here so the same logic the JobManager uses applies
        # in both the inline + promoted paths.
        try:
            resolved_shell = _resolve_shell(shell)
        except ZshRefused as e:
            return _err_envelope(command, str(e))

        if resolved_shell is not None:
            spawn_argv: list[str] = [resolved_shell, "-c", command]
        else:
            spawn_argv = list(argv) if isinstance(argv, list) else [str(argv)]

        start = time.monotonic()
        try:
            proc = subprocess.Popen(
                spawn_argv,
                cwd=cwd,
                env=full_env,
                stdin=subprocess.PIPE if stdin is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                preexec_fn=preexec,
                close_fds=True,
                bufsize=0,
            )
        except FileNotFoundError as e:
            return _err_envelope(command, f"command not found: {e}")
        except OSError as e:
            return _err_envelope(command, f"spawn failed: {e}")

        # Push stdin without blocking on the process draining it. For
        # large stdin payloads this would deadlock; for typical agent
        # use (small payloads or None) it's fine.
        if stdin is not None and proc.stdin is not None:
            try:
                proc.stdin.write(stdin.encode("utf-8"))
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass

        # Pump stdout/stderr into ring buffers so we don't deadlock on
        # full pipes during the wait. These same buffers become the
        # job's buffers if we auto-promote.
        stdout_buf = RingBuffer()
        stderr_buf = RingBuffer()
        pumps: list[threading.Thread] = []

        def _pump(stream, ring: RingBuffer) -> None:
            try:
                while True:
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                    ring.write(chunk)
            except (OSError, ValueError):
                pass
            finally:
                try:
                    stream.close()
                except Exception:
                    pass
                ring.close()

        if proc.stdout is not None:
            t = threading.Thread(target=_pump, args=(proc.stdout, stdout_buf), daemon=True)
            t.start()
            pumps.append(t)
        if proc.stderr is not None:
            t = threading.Thread(target=_pump, args=(proc.stderr, stderr_buf), daemon=True)
            t.start()
            pumps.append(t)

        # Wait for either: auto-bg budget, hard timeout, or natural exit.
        promoted = False
        timed_out = False
        budget = auto_background_after_sec if auto_background_after_sec > 0 else timeout_sec
        budget = min(budget, timeout_sec) if timeout_sec > 0 else budget

        try:
            proc.wait(timeout=budget if budget > 0 else None)
        except subprocess.TimeoutExpired:
            if auto_background_after_sec > 0:
                # Promote: the process keeps running, we hand its
                # already-pumping buffers to the JobManager.
                try:
                    record = get_manager().adopt_running(
                        proc,
                        spawn_argv if resolved_shell is None else command,
                        merged=False,
                        existing_stdout_buf=stdout_buf,
                        existing_stderr_buf=stderr_buf,
                        existing_pumps=pumps,
                    )
                    promoted = True
                    return build_exec_envelope(
                        command=command,
                        exit_code=None,
                        stdout_bytes=stdout_buf.tail(64 * 1024).data,
                        stderr_bytes=stderr_buf.tail(64 * 1024).data,
                        runtime_ms=int((time.monotonic() - start) * 1000),
                        pid=proc.pid,
                        timed_out=False,
                        max_output_kb=max_output_kb,
                        auto_backgrounded=True,
                        job_id=record.job_id,
                    )
                except JobLimitExceeded:
                    # Cap reached; treat as a hard timeout rather than spin.
                    pass
            # Fall through to hard-kill path.
            try:
                proc.terminate()
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            timed_out = True

        # Inline path: drain pump threads.
        for t in pumps:
            t.join(timeout=2.0)

        runtime_ms = int((time.monotonic() - start) * 1000)
        exit_code = proc.returncode if not promoted else None

        # The whole stream is in the ring; read from offset 0 to grab everything.
        stdout_full = stdout_buf.read(0, stdout_buf.total_written).data
        stderr_full = stderr_buf.read(0, stderr_buf.total_written).data

        return build_exec_envelope(
            command=command,
            exit_code=exit_code,
            stdout_bytes=stdout_full,
            stderr_bytes=stderr_full,
            runtime_ms=runtime_ms,
            pid=proc.pid,
            timed_out=timed_out,
            signaled=(exit_code is not None and exit_code < 0),
            max_output_kb=max_output_kb,
        )


def _err_envelope(command: str, message: str) -> dict:
    """Construct an envelope-shaped error reply for pre-spawn failures."""
    return {
        "exit_code": None,
        "stdout": "",
        "stderr": message,
        "stdout_truncated_bytes": 0,
        "stderr_truncated_bytes": 0,
        "runtime_ms": 0,
        "pid": None,
        "output_handle": None,
        "timed_out": False,
        "semantic_status": "error",
        "semantic_message": message,
        "warning": None,
        "auto_backgrounded": False,
        "job_id": None,
        "error": message,
    }


__all__ = ["register_exec_tools"]
