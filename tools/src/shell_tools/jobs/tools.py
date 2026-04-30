"""Job-control MCP tools: ``shell_job_start``, ``shell_job_logs``,
``shell_job_manage``.

Three tools, not seven: ``_logs`` rolls in status + wait, ``_manage``
covers list + signals + stdin so the agent has fewer tool names to
remember. Tradeoff is multi-action ``_manage`` is slightly less
self-documenting; the foundational skill compensates.
"""

from __future__ import annotations

import signal
from typing import TYPE_CHECKING, Any

from shell_tools.common.limits import coerce_limits, make_preexec_fn, sanitized_env
from shell_tools.jobs.manager import JobLimitExceeded, get_manager

if TYPE_CHECKING:
    from fastmcp import FastMCP


_SIGNAL_ALIASES = {
    "signal_term": signal.SIGTERM,
    "signal_kill": signal.SIGKILL,
    "signal_int": signal.SIGINT,
    "signal_hup": signal.SIGHUP,
    "signal_usr1": signal.SIGUSR1,
    "signal_usr2": signal.SIGUSR2,
}


def register_job_tools(mcp: FastMCP) -> None:
    manager = get_manager()

    @mcp.tool()
    def shell_job_start(
        command: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        merge_stderr: bool = False,
        shell: bool = False,
        name: str | None = None,
        limits: dict[str, int] | None = None,
    ) -> dict:
        """Spawn a background process. Returns a job_id you poll with shell_job_logs.

        Use this when work might run >1 minute, when you want to keep doing
        other things while it runs, or when you need to stream logs as they
        arrive. Jobs die when the shell-tools server restarts — they are NOT
        persistent across reboots.

        Args:
            command: Shell command to run. With shell=False, pass argv via the
                command string and we'll split on whitespace; for complex
                quoting use shell=True.
            cwd: Working directory. Default: server's cwd.
            env: Environment override. Merged into a sanitized base env (with
                zsh dotfile vars stripped).
            merge_stderr: When True, stderr is interleaved into stdout in a
                single ring buffer. Convenient for log-shaped output where
                ordering matters.
            shell: True to invoke /bin/bash -c. Refuses zsh.
            name: Optional human label surfaced in shell_job_manage(action="list").
            limits: Optional resource caps applied via setrlimit before exec.
                Keys: cpu_sec, rss_mb, fsize_mb, nofile.

        Returns: {job_id, pid, started_at}
        """
        try:
            # Build argv: for shell=False, naive split is fine for the common case;
            # the foundational skill steers complex commands toward shell=True.
            argv: list[str] | str
            if shell:
                argv = command
            else:
                argv = command.split()
                if not argv:
                    return {"error": "command was empty"}

            full_env = sanitized_env(env) if env is not None else None
            preexec = make_preexec_fn(coerce_limits(limits))
            record = manager.start(
                argv,
                cwd=cwd,
                env=full_env,
                shell=shell,
                merge_stderr=merge_stderr,
                name=name,
                preexec_fn=preexec,
            )
            return {
                "job_id": record.job_id,
                "pid": record.pid,
                "started_at": record.started_at,
                "name": record.name,
                "merged": merge_stderr,
            }
        except JobLimitExceeded as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    @mcp.tool()
    def shell_job_logs(
        job_id: str,
        stream: str = "stdout",
        since_offset: int = 0,
        max_bytes: int = 64000,
        wait_until_exit: bool = False,
        wait_timeout_sec: float = 30.0,
        tail: bool = False,
    ) -> dict:
        """Read job output at an offset. Combined read + status + wait primitive.

        Track next_offset across calls to avoid replaying data. When
        wait_until_exit=True, blocks server-side until the job exits or
        wait_timeout_sec elapses, then returns logs and final status.

        Args:
            job_id: From shell_job_start (or auto-promoted from shell_exec).
            stream: "stdout" | "stderr" | "merged". Use "merged" only when the
                job was started with merge_stderr=True.
            since_offset: Absolute byte offset to start reading from. Pass 0
                on first call; pass next_offset on subsequent calls.
            max_bytes: Max bytes of decoded output to return inline.
            wait_until_exit: When True, blocks until the job exits before reading.
            wait_timeout_sec: Cap on the wait. Returns whatever's accumulated.
            tail: When True, ignores since_offset and returns the last max_bytes.

        Returns: {data, offset, next_offset, status, exit_code, eof, truncated_bytes_dropped}
        """
        record = manager.get(job_id)
        if record is None:
            return {"error": f"unknown job_id: {job_id}"}

        if wait_until_exit:
            manager.wait(job_id, timeout_sec=wait_timeout_sec)
            record = manager.get(job_id) or record

        if stream == "merged":
            # Merged jobs always read from stdout_buf (which received both)
            buf = record.stdout_buf
        elif stream == "stderr":
            buf = record.stderr_buf
        else:
            buf = record.stdout_buf

        if buf is None:
            return {
                "error": f"stream={stream!r} not available (merge_stderr={record.merged})",
            }

        result = buf.tail(max_bytes) if tail else buf.read(since_offset, max_bytes)
        return {
            "data": result.data.decode("utf-8", errors="replace"),
            "offset": result.offset,
            "next_offset": result.next_offset,
            "truncated_bytes_dropped": result.truncated_bytes_dropped,
            "eof": buf.eof and result.next_offset >= buf.total_written,
            "status": record.status,
            "exit_code": record.exit_code,
            "runtime_ms": record.runtime_ms(),
        }

    @mcp.tool()
    def shell_job_manage(
        action: str,
        job_id: str | None = None,
        data: str | None = None,
    ) -> dict:
        """List jobs, send signals, or write to job stdin.

        Single tool covering job-control side effects. The action argument
        picks the operation:

        - "list": list active + recently-exited jobs. job_id ignored.
        - "signal_term" | "signal_kill" | "signal_int" | "signal_hup"
        | "signal_usr1" | "signal_usr2": send the named signal. Requires job_id.
        - "stdin": write `data` to the job's stdin. Requires job_id and data.
        - "close_stdin": close the job's stdin pipe (e.g. to flush a tool that
        reads until EOF). Requires job_id.

        Signal escalation idiom (foundational skill teaches this): try
        signal_int first (graceful), then signal_term after a few seconds, then
        signal_kill as a last resort. The OS may take a moment to deliver.

        Returns vary by action. List → {jobs: [...]}. Signals → {ok, signal}.
        Stdin → {bytes_written}.
        """
        if action == "list":
            return {"jobs": manager.list()}

        if not job_id:
            return {"error": f"action={action!r} requires job_id"}

        if action in _SIGNAL_ALIASES:
            ok = manager.signal(job_id, _SIGNAL_ALIASES[action])
            return {"ok": ok, "signal": action.removeprefix("signal_").upper()}

        if action == "stdin":
            if data is None:
                return {"error": "action=stdin requires data"}
            n = manager.write_stdin(job_id, data.encode("utf-8"))
            return {"bytes_written": n}

        if action == "close_stdin":
            return {"ok": manager.close_stdin(job_id)}

        return {"error": f"unknown action: {action!r}"}

    # Expose a non-tool reference so the lifespan hook can shutdown_all().
    register_job_tools.manager = manager  # type: ignore[attr-defined]


def get_registered_manager() -> Any:
    """Return the JobManager registered for the most recent FastMCP setup.
    Used by the server lifespan to reap on shutdown."""
    return get_manager()


__all__ = ["register_job_tools", "get_registered_manager"]
