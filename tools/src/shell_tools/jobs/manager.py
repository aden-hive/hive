"""Background job manager.

Owns the long-lived ``Popen`` instances backing ``shell_job_*`` and
``shell_exec`` auto-promotion. Each job has up to two ring buffers
(stdout / stderr, or one merged) fed by background pump threads.

Design notes:
  - We don't use asyncio here. FastMCP's tool handlers run in a worker
    thread; subprocess + threads compose more naturally with that
    model than asyncio Subprocess (which would need its own loop).
  - ``shell_exec`` "promotes" by adopting an already-running Popen
    into the manager — it doesn't re-spawn. The pump threads were
    already filling buffers in the exec path.
  - Hard concurrency cap (env: ``SHELL_TOOLS_MAX_JOBS``, default 32).
    The cap is the only non-bypassable safety pin per the soft-
    guardrails design.
  - On server shutdown the lifespan hook calls ``shutdown_all()``
    which TERMs every child, waits 2s, then KILLs. Eliminates
    orphans.
"""

from __future__ import annotations

import os
import secrets
import signal
import subprocess
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from shell_tools.common.ring_buffer import RingBuffer

_MAX_JOBS_DEFAULT = 32
_DEFAULT_RING_BYTES = 4 * 1024 * 1024
_RECENT_EXIT_KEEP = 50  # exited jobs we still surface to ``shell_job_manage(action="list")``


@dataclass(slots=True)
class JobRecord:
    job_id: str
    pid: int
    name: str
    command: str | list[str]
    started_at: float
    proc: subprocess.Popen[bytes]
    stdout_buf: RingBuffer | None
    stderr_buf: RingBuffer | None
    merged: bool
    pumps: list[threading.Thread] = field(default_factory=list)
    exited_at: float | None = None
    exit_code: int | None = None
    signaled: bool = False
    # Adopted=True when the job started life as a foreground shell_exec
    # and was promoted past the auto-background budget.
    adopted: bool = False

    @property
    def status(self) -> str:
        return "exited" if self.exited_at is not None else "running"

    def runtime_ms(self) -> int:
        end = self.exited_at if self.exited_at is not None else time.monotonic()
        return int((end - self.started_at) * 1000)

    def to_summary(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "pid": self.pid,
            "name": self.name,
            "command": self.command,
            "started_at": self.started_at,
            "status": self.status,
            "exit_code": self.exit_code,
            "runtime_ms": self.runtime_ms(),
            "merged": self.merged,
            "stdout_bytes": (self.stdout_buf.total_written if self.stdout_buf else 0),
            "stderr_bytes": (self.stderr_buf.total_written if self.stderr_buf else 0),
            "adopted": self.adopted,
        }


class JobLimitExceeded(RuntimeError):
    """Raised when the per-server concurrent-job cap would be exceeded."""


class JobManager:
    def __init__(self, max_jobs: int | None = None, ring_bytes: int = _DEFAULT_RING_BYTES):
        self._max_jobs = max_jobs or int(os.getenv("SHELL_TOOLS_MAX_JOBS", str(_MAX_JOBS_DEFAULT)))
        self._ring_bytes = ring_bytes
        self._jobs: dict[str, JobRecord] = {}
        # FIFO of recently-exited job_ids so list/inspect can still
        # find them for a while after exit.
        self._exited_order: list[str] = []
        self._lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for j in self._jobs.values() if j.exited_at is None)

    def start(
        self,
        command: str | Sequence[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        shell: bool | str = False,
        merge_stderr: bool = False,
        name: str | None = None,
        preexec_fn=None,
    ) -> JobRecord:
        """Spawn a process and start pumping its output into ring buffers."""
        if self.active_count() >= self._max_jobs:
            raise JobLimitExceeded(
                f"shell-tools job cap reached ({self._max_jobs}). "
                "Wait for a job to finish or raise SHELL_TOOLS_MAX_JOBS."
            )

        proc = self._spawn(command, cwd=cwd, env=env, shell=shell, merge_stderr=merge_stderr, preexec_fn=preexec_fn)
        record = self._adopt(proc, command, name=name, merged=merge_stderr)
        return record

    def adopt_running(
        self,
        proc: subprocess.Popen[bytes],
        command: str | Sequence[str],
        *,
        name: str | None = None,
        merged: bool = False,
        existing_stdout_buf: RingBuffer | None = None,
        existing_stderr_buf: RingBuffer | None = None,
        existing_pumps: list[threading.Thread] | None = None,
    ) -> JobRecord:
        """Adopt a Popen that's already running with pumps in flight.

        Used by ``shell_exec`` for auto-promotion: the foreground path
        had already started pump threads filling its own ring buffers.
        We hand the buffers + pumps over to the manager so the agent
        can resume reading via ``shell_job_logs``.
        """
        if self.active_count() >= self._max_jobs:
            # Mid-call cap exceeded — kill and report.
            try:
                proc.terminate()
            except Exception:
                pass
            raise JobLimitExceeded(
                f"shell-tools job cap reached ({self._max_jobs}); foreground exec was killed during auto-promotion."
            )
        record = self._wrap(
            proc,
            command,
            name=name,
            merged=merged,
            stdout_buf=existing_stdout_buf,
            stderr_buf=existing_stderr_buf,
            pumps=existing_pumps,
            adopted=True,
        )
        with self._lock:
            self._jobs[record.job_id] = record
        # Watcher only — pumps already running.
        threading.Thread(target=self._watch_for_exit, args=(record,), daemon=True).start()
        return record

    def get(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[dict]:
        with self._lock:
            jobs = list(self._jobs.values())
        # Recent first — running, then exited by exit time descending
        jobs.sort(
            key=lambda j: (j.exited_at is not None, -(j.exited_at or j.started_at)),
        )
        return [j.to_summary() for j in jobs]

    def signal(self, job_id: str, signum: int) -> bool:
        record = self.get(job_id)
        if record is None or record.exited_at is not None:
            return False
        try:
            record.proc.send_signal(signum)
            return True
        except (ProcessLookupError, OSError):
            return False

    def write_stdin(self, job_id: str, data: bytes, *, close_after: bool = False) -> int:
        record = self.get(job_id)
        if record is None or record.proc.stdin is None or record.exited_at is not None:
            return 0
        try:
            n = record.proc.stdin.write(data)
            record.proc.stdin.flush()
            if close_after:
                record.proc.stdin.close()
            return int(n or len(data))
        except (BrokenPipeError, OSError):
            return 0

    def close_stdin(self, job_id: str) -> bool:
        record = self.get(job_id)
        if record is None or record.proc.stdin is None:
            return False
        try:
            record.proc.stdin.close()
            return True
        except OSError:
            return False

    def wait(self, job_id: str, timeout_sec: float | None = None) -> JobRecord | None:
        """Block until the job exits or ``timeout_sec`` elapses. Returns
        the (possibly still-running) record so callers can read final state."""
        record = self.get(job_id)
        if record is None:
            return None
        try:
            record.proc.wait(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            pass
        return record

    def shutdown_all(self, grace_sec: float = 2.0) -> None:
        """SIGTERM every running job, wait ``grace_sec``, then SIGKILL.
        Called from the FastMCP lifespan hook. Idempotent."""
        with self._lock:
            running = [j for j in self._jobs.values() if j.exited_at is None]
        for record in running:
            try:
                record.proc.terminate()
            except Exception:
                pass
        deadline = time.monotonic() + grace_sec
        while time.monotonic() < deadline and any(j.proc.poll() is None for j in running):
            time.sleep(0.05)
        for record in running:
            if record.proc.poll() is None:
                try:
                    record.proc.kill()
                except Exception:
                    pass

    # ── Internals ─────────────────────────────────────────────────

    def _spawn(
        self,
        command: str | Sequence[str],
        *,
        cwd: str | None,
        env: dict[str, str] | None,
        shell: bool | str,
        merge_stderr: bool,
        preexec_fn,
    ) -> subprocess.Popen[bytes]:
        # Resolve shell: a string shell is coerced to ``[<shell>, "-c", command]``,
        # bool=True means /bin/bash with the same shape.
        from shell_tools.common.limits import _resolve_shell

        resolved = _resolve_shell(shell)
        if resolved is not None:
            if isinstance(command, (list, tuple)):
                command_str = " ".join(str(c) for c in command)
            else:
                command_str = str(command)
            argv: list[str] = [resolved, "-c", command_str]
            shell_arg = False
        else:
            argv = list(command) if isinstance(command, (list, tuple)) else command  # type: ignore[assignment]
            shell_arg = False

        return subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=(subprocess.STDOUT if merge_stderr else subprocess.PIPE),
            shell=shell_arg,
            preexec_fn=preexec_fn,
            close_fds=True,
            bufsize=0,
        )

    def _adopt(
        self,
        proc: subprocess.Popen[bytes],
        command: str | Sequence[str],
        *,
        name: str | None,
        merged: bool,
    ) -> JobRecord:
        stdout_buf = RingBuffer(self._ring_bytes)
        stderr_buf = None if merged else RingBuffer(self._ring_bytes)

        record = self._wrap(proc, command, name=name, merged=merged, stdout_buf=stdout_buf, stderr_buf=stderr_buf)
        with self._lock:
            self._jobs[record.job_id] = record

        # Start pumps + watcher
        if proc.stdout is not None:
            t = threading.Thread(
                target=_pump_stream,
                args=(proc.stdout, stdout_buf),
                daemon=True,
                name=f"shell-job-stdout-{record.job_id}",
            )
            t.start()
            record.pumps.append(t)
        if not merged and proc.stderr is not None and stderr_buf is not None:
            t = threading.Thread(
                target=_pump_stream,
                args=(proc.stderr, stderr_buf),
                daemon=True,
                name=f"shell-job-stderr-{record.job_id}",
            )
            t.start()
            record.pumps.append(t)
        threading.Thread(target=self._watch_for_exit, args=(record,), daemon=True).start()
        return record

    def _wrap(
        self,
        proc: subprocess.Popen[bytes],
        command: str | Sequence[str],
        *,
        name: str | None,
        merged: bool,
        stdout_buf: RingBuffer | None = None,
        stderr_buf: RingBuffer | None = None,
        pumps: list[threading.Thread] | None = None,
        adopted: bool = False,
    ) -> JobRecord:
        return JobRecord(
            job_id="job_" + secrets.token_hex(6),
            pid=proc.pid,
            name=name or _default_name(command),
            command=list(command) if isinstance(command, (list, tuple)) else str(command),
            started_at=time.monotonic(),
            proc=proc,
            stdout_buf=stdout_buf,
            stderr_buf=stderr_buf,
            merged=merged,
            pumps=pumps or [],
            adopted=adopted,
        )

    def _watch_for_exit(self, record: JobRecord) -> None:
        rc = record.proc.wait()
        # Drain any final bytes — pump threads exit on EOF, so this is
        # mostly a join; we don't need to actively pull.
        for pump in record.pumps:
            pump.join(timeout=2.0)
        if record.stdout_buf is not None:
            record.stdout_buf.close()
        if record.stderr_buf is not None:
            record.stderr_buf.close()
        with self._lock:
            record.exited_at = time.monotonic()
            record.exit_code = rc
            record.signaled = rc < 0 or (rc != 0 and abs(rc) in _SIGNAL_NUMBERS)
            self._exited_order.append(record.job_id)
            self._evict_old_exits_locked()

    def _evict_old_exits_locked(self) -> None:
        while len(self._exited_order) > _RECENT_EXIT_KEEP:
            old_id = self._exited_order.pop(0)
            self._jobs.pop(old_id, None)


def _pump_stream(stream, ring: RingBuffer) -> None:
    """Read bytes from ``stream`` until EOF; push into ``ring``."""
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


def _default_name(command: str | Sequence[str]) -> str:
    if isinstance(command, (list, tuple)):
        return command[0] if command else "job"
    text = str(command).strip().split()
    return text[0] if text else "job"


_SIGNAL_NUMBERS = {
    signal.SIGINT,
    signal.SIGTERM,
    signal.SIGKILL,
    signal.SIGHUP,
    signal.SIGUSR1,
    signal.SIGUSR2,
}


# Module-level singleton.
_MANAGER: JobManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_manager() -> JobManager:
    global _MANAGER
    if _MANAGER is None:
        with _MANAGER_LOCK:
            if _MANAGER is None:
                _MANAGER = JobManager()
    return _MANAGER


__all__ = ["JobManager", "JobRecord", "JobLimitExceeded", "get_manager"]
