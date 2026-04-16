"""In-process registry of long-running shell jobs spawned by
``execute_command_tool(run_in_background=True)``.

Jobs are keyed on a short id the tool returns to the agent. The agent
can then call ``bash_output(id=...)`` to poll for new output and
``bash_kill(id=...)`` to terminate. Each job is scoped to an
``agent_id`` so two agents sharing the same MCP server can't see or
kill each other's work.

The stdout/stderr buffers are bounded rolling tail buffers (64 KB each)
so a runaway process can't exhaust memory. Older bytes are dropped with
a one-time ``[truncated N bytes]`` marker prepended to the returned
text.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from uuid import uuid4

from ..command_sanitizer import CommandBlockedError, validate_command  # noqa: F401

# 64 KB rolling window per stream. Large enough for long build logs,
# small enough that a bash infinite loop can't OOM the MCP process.
_MAX_BUFFER_BYTES = 64 * 1024


@dataclass
class _RingBuffer:
    """Append-only byte buffer with a hard byte ceiling and per-read
    offset tracking so each bash_output call only returns new bytes.
    """

    max_bytes: int = _MAX_BUFFER_BYTES
    # deque of (global_offset, bytes) chunks. global_offset is the total
    # bytes written prior to this chunk; lets us compute "bytes since
    # last poll" without copying.
    _chunks: deque[tuple[int, bytes]] = field(default_factory=deque)
    _total_written: int = 0
    _total_dropped: int = 0
    _read_cursor: int = 0

    def write(self, data: bytes) -> None:
        if not data:
            return
        self._chunks.append((self._total_written, data))
        self._total_written += len(data)
        # Evict from the front until we're under the ceiling.
        current_bytes = sum(len(c) for _, c in self._chunks)
        while current_bytes > self.max_bytes and self._chunks:
            dropped_offset, dropped = self._chunks.popleft()
            self._total_dropped += len(dropped)
            current_bytes -= len(dropped)
            # Push the read cursor forward if the reader was still
            # pointing at bytes we just evicted.
            if self._read_cursor < dropped_offset + len(dropped):
                self._read_cursor = dropped_offset + len(dropped)

    def read_new(self) -> str:
        """Return any bytes since the last call, as decoded text.

        Includes a ``[truncated N bytes]`` prefix if rolling-window
        eviction dropped any bytes the reader hadn't yet consumed.
        """
        chunks_out: list[bytes] = []
        cursor = self._read_cursor
        for offset, chunk in self._chunks:
            end = offset + len(chunk)
            if end <= cursor:
                continue
            start_in_chunk = max(0, cursor - offset)
            chunks_out.append(chunk[start_in_chunk:])
            cursor = end
        self._read_cursor = cursor
        raw = b"".join(chunks_out)
        text = raw.decode("utf-8", errors="replace")
        # Surface eviction ONCE per poll so the agent knows to check
        # the file system for larger logs instead of assuming it's got
        # the full output.
        if self._total_dropped > 0 and text:
            text = f"[truncated {self._total_dropped} earlier bytes]\n" + text
        return text


@dataclass
class BackgroundJob:
    id: str
    agent_id: str
    command: str
    cwd: str
    started_at: float
    process: asyncio.subprocess.Process
    stdout_buf: _RingBuffer = field(default_factory=_RingBuffer)
    stderr_buf: _RingBuffer = field(default_factory=_RingBuffer)
    _pump_task: asyncio.Task | None = None
    exit_code: int | None = None

    def status(self) -> str:
        if self.exit_code is not None:
            return f"exited({self.exit_code})"
        if self.process.returncode is not None:
            # Not yet surfaced by the pump but already finished.
            return f"exited({self.process.returncode})"
        return "running"


# agent_id -> {job_id -> BackgroundJob}
_jobs: dict[str, dict[str, BackgroundJob]] = {}
_jobs_lock = asyncio.Lock()


def _short_id() -> str:
    return uuid4().hex[:8]


async def _pump(job: BackgroundJob) -> None:
    """Drain the child process's stdout/stderr into the ring buffers."""
    proc = job.process

    async def _drain(stream: asyncio.StreamReader | None, buf: _RingBuffer) -> None:
        if stream is None:
            return
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                return
            buf.write(chunk)

    await asyncio.gather(
        _drain(proc.stdout, job.stdout_buf),
        _drain(proc.stderr, job.stderr_buf),
    )
    job.exit_code = await proc.wait()


async def spawn(command: str, cwd: str, agent_id: str) -> BackgroundJob:
    """Start a subprocess in the background and register it. The caller
    holds the job id returned from here and can poll via ``get()``.

    Defense-in-depth: ``validate_command`` is called here even though the
    public entrypoint (``execute_command_tool``) already validates before
    calling ``spawn``. This makes the function self-defending so future
    callers, test fixtures, or internal refactors cannot bypass the
    safety guardrail by invoking ``spawn`` directly.
    """
    validate_command(command)

    proc = await asyncio.create_subprocess_shell(
        command,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    job = BackgroundJob(
        id=_short_id(),
        agent_id=agent_id,
        command=command,
        cwd=cwd,
        started_at=time.time(),
        process=proc,
    )
    # Start pumping IO in the background so the ring buffers stay warm
    # even if the agent doesn't poll for a while.
    job._pump_task = asyncio.create_task(_pump(job))

    async with _jobs_lock:
        _jobs.setdefault(agent_id, {})[job.id] = job
    return job


async def get(agent_id: str, job_id: str) -> BackgroundJob | None:
    async with _jobs_lock:
        return _jobs.get(agent_id, {}).get(job_id)


async def kill(agent_id: str, job_id: str, grace_seconds: float = 3.0) -> str:
    """SIGTERM a background job, escalating to SIGKILL after a grace
    period. Returns a human-readable status string.
    """
    job = await get(agent_id, job_id)
    if job is None:
        return f"no background job with id '{job_id}'"
    if job.process.returncode is not None:
        status = f"already exited with code {job.process.returncode}"
    else:
        try:
            job.process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(job.process.wait(), timeout=grace_seconds)
            status = f"terminated cleanly (exit={job.process.returncode})"
        except TimeoutError:
            try:
                job.process.kill()
            except ProcessLookupError:
                pass
            await job.process.wait()
            status = f"killed (SIGKILL, exit={job.process.returncode})"
    # Deregister after kill so the id is no longer reachable.
    async with _jobs_lock:
        scope = _jobs.get(agent_id)
        if scope is not None:
            scope.pop(job_id, None)
    return status


async def clear_agent(agent_id: str) -> None:
    """Test hook: kill every job owned by ``agent_id``."""
    async with _jobs_lock:
        scope = _jobs.pop(agent_id, {})
    for job in scope.values():
        if job.process.returncode is None:
            try:
                job.process.kill()
            except ProcessLookupError:
                pass
            await job.process.wait()
