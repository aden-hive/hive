"""Persistent PTY-backed bash sessions.

Built on stdlib ``pty.openpty()`` + ``os.fork()``. A reader thread
fills a ring buffer; the public API exposes three modes:

  - ``run(command, timeout_sec)``: write the command, wait for the
    unique prompt sentinel (or an ``expect=`` regex override), return
    everything in between.
  - ``send_raw(data)``: write bytes, no waiting. For REPLs / vim /
    sudo-prompt-style flows.
  - ``drain(timeout_sec)``: read whatever's currently buffered (after
    a raw send).

A unique ``PS1`` sentinel is set at session start so ``run()`` can
unambiguously detect command completion. Per-session concurrency is
serialized: a busy session refuses concurrent ``run()`` calls.

POSIX-only: imports stdlib ``pty`` which doesn't exist on Windows.
"""

from __future__ import annotations

import errno
import fcntl
import os
import pty
import re
import select
import signal
import struct
import termios
import threading
import time
import uuid

from shell_tools.common.limits import _resolve_shell, sanitized_env
from shell_tools.common.ring_buffer import RingBuffer

_BUF_BYTES = 2 * 1024 * 1024


class SessionBusy(RuntimeError):
    """Raised when a concurrent run() attempts to use a session that's already executing."""


class PtySession:
    """One persistent bash session bound to a PTY.

    Thread-safe for the disjoint-mode operations: ``run`` serializes via
    ``_busy_lock``, ``send_raw`` and ``drain`` use the ring's own lock.
    """

    def __init__(
        self,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        shell: bool | str = True,
        cols: int = 120,
        rows: int = 40,
        idle_timeout_sec: int = 1800,
    ):
        self.session_id = "pty_" + uuid.uuid4().hex[:10]
        self.shell_path = _resolve_shell(shell) or "/bin/bash"
        self._sentinel_token = uuid.uuid4().hex
        self._sentinel = f"__SHELLTOOLS_PROMPT_{self._sentinel_token}__"
        self._sentinel_re = re.compile(re.escape(self._sentinel))

        # Build env: zsh leakage stripped, prompt set to our sentinel.
        merged_env = sanitized_env(env)
        merged_env["PS1"] = f"{self._sentinel}\n$ "
        merged_env["PS2"] = ""
        merged_env["PROMPT_COMMAND"] = ""  # don't let user dotfiles override PS1
        merged_env["TERM"] = merged_env.get("TERM", "xterm-256color")

        self._created_at = time.monotonic()
        self._last_activity = self._created_at
        self.idle_timeout_sec = idle_timeout_sec

        self._pid, self._fd = pty.fork()
        if self._pid == 0:
            # Child — exec bash. --norc --noprofile keeps things
            # predictable; the foundational skill teaches that the
            # session runs vanilla bash, not the user's interactive
            # shell.
            try:
                if cwd:
                    os.chdir(cwd)
                argv = [self.shell_path, "--norc", "--noprofile", "-i"]
                os.execve(self.shell_path, argv, merged_env)
            except Exception as e:  # pragma: no cover — child exec
                os.write(2, f"shell-tools pty: exec failed: {e}\n".encode())
                os._exit(127)

        # Parent
        _set_pty_size(self._fd, rows, cols)
        _set_nonblocking(self._fd)

        self._buf = RingBuffer(_BUF_BYTES)
        self._busy_lock = threading.Lock()
        self._closed = threading.Event()

        self._reader = threading.Thread(target=self._read_loop, daemon=True, name=f"pty-reader-{self.session_id}")
        self._reader.start()

        # Wait for the first prompt so the session is "ready" before we return.
        # If bash --norc somehow doesn't print one, give up after 2 seconds —
        # the session is still usable, it just won't have a prompt-aligned
        # initial offset.
        self._wait_for_sentinel(timeout_sec=2.0, since_offset=0)

    # ── Public API ────────────────────────────────────────────────

    @property
    def pid(self) -> int:
        return self._pid

    def is_alive(self) -> bool:
        if self._closed.is_set():
            return False
        try:
            pid, _ = os.waitpid(self._pid, os.WNOHANG)
            return pid == 0
        except ChildProcessError:
            return False

    def run(self, command: str, *, expect: str | None = None, timeout_sec: float = 60.0) -> dict:
        """Send ``command`` + newline, wait for the prompt sentinel
        (or ``expect`` regex override), return the slice in between."""
        if not self._busy_lock.acquire(blocking=False):
            raise SessionBusy(f"session {self.session_id} is busy")
        try:
            start_offset = self._buf.total_written
            self._write(command.encode("utf-8") + b"\n")
            self._last_activity = time.monotonic()
            return self._wait_for_sentinel(
                timeout_sec=timeout_sec,
                since_offset=start_offset,
                expect_pattern=expect,
            )
        finally:
            self._busy_lock.release()

    def send_raw(self, data: str, *, add_newline: bool = False) -> int:
        """Write bytes without waiting for prompt. For REPLs/vim/sudo prompts."""
        payload = data.encode("utf-8")
        if add_newline:
            payload += b"\n"
        n = self._write(payload)
        self._last_activity = time.monotonic()
        return n

    def drain(self, *, timeout_sec: float = 2.0, max_bytes: int = 64000) -> dict:
        """Read whatever's currently buffered. Used after send_raw to capture
        REPL / interactive-program output."""
        deadline = time.monotonic() + timeout_sec
        last_total = self._buf.total_written
        # Wait for activity to settle for a brief window — gives the
        # process a chance to finish its current line.
        while time.monotonic() < deadline:
            time.sleep(0.05)
            current = self._buf.total_written
            if current == last_total:
                break
            last_total = current

        result = self._buf.tail(max_bytes)
        return {
            "output": result.data.decode("utf-8", errors="replace"),
            "more": result.next_offset < self._buf.total_written,
            "offset": result.offset,
            "next_offset": result.next_offset,
            "timed_out": False,
        }

    def close(self, *, force: bool = False, grace_sec: float = 1.0) -> dict:
        """Terminate the session. Returns final output."""
        if self._closed.is_set():
            return {"exit_code": None, "final_output": "", "already_closed": True}

        # Flush an exit if not forcing.
        if not force:
            try:
                self._write(b"exit\n")
            except OSError:
                pass

        deadline = time.monotonic() + grace_sec
        while time.monotonic() < deadline:
            try:
                pid, status = os.waitpid(self._pid, os.WNOHANG)
                if pid != 0:
                    break
            except ChildProcessError:
                break
            time.sleep(0.05)

        try:
            os.kill(self._pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            os.waitpid(self._pid, os.WNOHANG)
        except ChildProcessError:
            pass

        if self.is_alive():
            try:
                os.kill(self._pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

        self._closed.set()
        try:
            os.close(self._fd)
        except OSError:
            pass

        # Final output = whatever's still in the ring.
        result = self._buf.tail(64 * 1024)
        try:
            _pid, status = os.waitpid(self._pid, os.WNOHANG)
            exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else None
        except ChildProcessError:
            exit_code = None
        return {
            "exit_code": exit_code,
            "final_output": result.data.decode("utf-8", errors="replace"),
            "already_closed": False,
        }

    def to_summary(self) -> dict:
        return {
            "session_id": self.session_id,
            "pid": self._pid,
            "shell": self.shell_path,
            "alive": self.is_alive(),
            "idle_sec": int(time.monotonic() - self._last_activity),
            "created_at": self._created_at,
        }

    # ── Internals ─────────────────────────────────────────────────

    def _write(self, data: bytes) -> int:
        if self._closed.is_set():
            raise OSError("session is closed")
        try:
            return os.write(self._fd, data)
        except OSError as e:
            if e.errno == errno.EAGAIN:
                # PTY is full — retry briefly.
                deadline = time.monotonic() + 1.0
                while time.monotonic() < deadline:
                    time.sleep(0.01)
                    try:
                        return os.write(self._fd, data)
                    except OSError:
                        continue
            raise

    def _read_loop(self) -> None:
        while not self._closed.is_set():
            try:
                ready, _, _ = select.select([self._fd], [], [], 0.5)
            except (OSError, ValueError):
                break
            if not ready:
                # Periodically check for child death even when no data.
                try:
                    pid, _ = os.waitpid(self._pid, os.WNOHANG)
                    if pid != 0:
                        break
                except ChildProcessError:
                    break
                continue
            try:
                chunk = os.read(self._fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            self._buf.write(chunk)
        self._buf.close()
        self._closed.set()

    def _wait_for_sentinel(
        self,
        *,
        timeout_sec: float,
        since_offset: int,
        expect_pattern: str | None = None,
    ) -> dict:
        """Poll the buffer until we see the sentinel (or expect pattern)."""
        deadline = time.monotonic() + timeout_sec
        pattern: re.Pattern[str] | None = None
        if expect_pattern is not None:
            pattern = re.compile(expect_pattern)

        prompt_offset = since_offset
        while time.monotonic() < deadline:
            slice_ = self._buf.read(since_offset, self._buf.total_written - since_offset)
            text = slice_.data.decode("utf-8", errors="replace")
            if pattern is not None:
                m = pattern.search(text)
                if m is not None:
                    output = text[: m.start()]
                    prompt_offset = since_offset + len(text[: m.end()].encode("utf-8", errors="replace"))
                    return {
                        "output": output,
                        "prompt_after": True,
                        "matched_expect": True,
                        "next_offset": prompt_offset,
                        "timed_out": False,
                    }
            else:
                m = self._sentinel_re.search(text)
                if m is not None:
                    output = text[: m.start()]
                    # Strip the trailing echoed command/newline above the sentinel
                    output = _strip_command_echo(output)
                    return {
                        "output": output,
                        "prompt_after": True,
                        "matched_expect": False,
                        "next_offset": since_offset + len(text[: m.end()].encode("utf-8", errors="replace")),
                        "timed_out": False,
                    }
            time.sleep(0.05)
            if self._closed.is_set():
                break

        # Timed out — return whatever we have.
        slice_ = self._buf.read(since_offset, self._buf.total_written - since_offset)
        return {
            "output": slice_.data.decode("utf-8", errors="replace"),
            "prompt_after": False,
            "matched_expect": False,
            "next_offset": slice_.next_offset,
            "timed_out": True,
        }


def _set_pty_size(fd: int, rows: int, cols: int) -> None:
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError:
        pass


def _set_nonblocking(fd: int) -> None:
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)


def _strip_command_echo(text: str) -> str:
    """Drop the first line if it looks like the echoed command. PTYs in
    canonical mode echo the user's input back; we want only the program's
    output. Best-effort heuristic — leaves the text alone if uncertain."""
    if "\n" in text:
        first, rest = text.split("\n", 1)
        # Keep only the rest if the first line is short (likely the echo).
        if len(first) < 4096:
            return rest
    return text


__all__ = ["PtySession", "SessionBusy"]
