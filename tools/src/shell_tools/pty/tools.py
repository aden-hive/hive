"""Three PTY tools: ``shell_pty_open``, ``shell_pty_run``, ``shell_pty_close``.

Per-server hard cap on concurrent sessions (env: ``SHELL_TOOLS_MAX_PTY``,
default 8) prevents PTY exhaustion. Idle sessions older than
``idle_timeout_sec`` are reaped lazily on every ``_open`` so an
abandoned session can't leak a bash forever.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from typing import TYPE_CHECKING

from shell_tools.common.limits import ZshRefused

if TYPE_CHECKING:
    from fastmcp import FastMCP


_MAX_PTY_DEFAULT = 8


class _PtyRegistry:
    def __init__(self):
        self._sessions: dict[str, PtySession] = {}  # noqa: F821
        self._lock = threading.Lock()
        self._max = int(os.getenv("SHELL_TOOLS_MAX_PTY", str(_MAX_PTY_DEFAULT)))

    def reap_idle(self) -> None:
        """Drop sessions whose idle time exceeded their idle_timeout_sec."""
        with self._lock:
            now = time.monotonic()
            stale = [
                sid
                for sid, sess in self._sessions.items()
                if not sess.is_alive() or (now - sess._last_activity) > sess.idle_timeout_sec
            ]
        for sid in stale:
            sess = self._sessions.pop(sid, None)
            if sess is not None:
                try:
                    sess.close(force=True, grace_sec=0.5)
                except Exception:
                    pass

    def count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def add(self, sess) -> None:
        with self._lock:
            if len(self._sessions) >= self._max:
                # Caller should have reaped first; treat as cap.
                raise RuntimeError(
                    f"shell-tools PTY cap reached ({self._max}). "
                    "Close idle sessions or raise SHELL_TOOLS_MAX_PTY."
                )
            self._sessions[sess.session_id] = sess

    def get(self, sid: str):
        with self._lock:
            return self._sessions.get(sid)

    def remove(self, sid: str) -> None:
        with self._lock:
            self._sessions.pop(sid, None)

    def list(self) -> list[dict]:
        with self._lock:
            return [s.to_summary() for s in self._sessions.values()]

    def shutdown_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for sess in sessions:
            try:
                sess.close(force=True, grace_sec=0.5)
            except Exception:
                pass


_REGISTRY = _PtyRegistry()


def get_registry() -> _PtyRegistry:
    return _REGISTRY


def register_pty_tools(mcp: FastMCP) -> None:
    if sys.platform == "win32":
        # Register stub tools that report unsupported; keeps the tool
        # surface uniform across platforms even when PTY is unavailable.
        @mcp.tool()
        def shell_pty_open(*args, **kwargs) -> dict:
            """Persistent PTY-backed bash session. POSIX-only.

            Windows is not supported in v1 — use shell_exec / shell_job_*
            for non-interactive work. The PTY tools require stdlib pty,
            which exists only on Linux + macOS.
            """
            return {"error": "shell_pty_* tools are POSIX-only; not supported on Windows"}

        @mcp.tool()
        def shell_pty_run(*args, **kwargs) -> dict:  # noqa: D401
            """Persistent PTY-backed bash session. POSIX-only."""
            return {"error": "shell_pty_* tools are POSIX-only; not supported on Windows"}

        @mcp.tool()
        def shell_pty_close(*args, **kwargs) -> dict:  # noqa: D401
            """Persistent PTY-backed bash session. POSIX-only."""
            return {"error": "shell_pty_* tools are POSIX-only; not supported on Windows"}

        return

    from shell_tools.pty.session import PtySession, SessionBusy

    @mcp.tool()
    def shell_pty_open(
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        cols: int = 120,
        rows: int = 40,
        idle_timeout_sec: int = 1800,
    ) -> dict:
        """Open a persistent /bin/bash session in a PTY.

        Use a session when you need state across calls — building env vars,
        navigating with cd, driving REPLs, or responding to interactive
        prompts (sudo, ssh, mysql). For one-shot work, use shell_exec
        instead.

        The session runs vanilla bash (--norc --noprofile) so dotfiles
        don't surprise you. A unique PS1 sentinel is set so shell_pty_run
        can unambiguously detect command completion. macOS users: this
        is /bin/bash, not zsh, by deliberate policy — explicit
        shell="/bin/zsh" overrides are rejected.

        Args:
            cwd: Initial working directory.
            env: Environment override (zsh dotfile vars are stripped).
            cols, rows: Terminal size.
            idle_timeout_sec: Drop the session after this many seconds idle.

        Returns: {session_id, pid, shell}
        """
        _REGISTRY.reap_idle()
        try:
            sess = PtySession(cwd=cwd, env=env, cols=cols, rows=rows, idle_timeout_sec=idle_timeout_sec)
        except ZshRefused as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"failed to open session: {type(e).__name__}: {e}"}
        try:
            _REGISTRY.add(sess)
        except RuntimeError as e:
            sess.close(force=True, grace_sec=0.2)
            return {"error": str(e)}
        return {
            "session_id": sess.session_id,
            "pid": sess.pid,
            "shell": sess.shell_path,
        }

    @mcp.tool()
    def shell_pty_run(
        session_id: str,
        command: str | None = None,
        expect: str | None = None,
        raw_send: bool = False,
        read_only: bool = False,
        timeout_sec: float = 60.0,
    ) -> dict:
        """Run a command in a session, send raw input, or drain output.

        Three modes:
        - Default: pass a command. The session sends it, waits for the
            unique prompt sentinel (or `expect` regex if provided), and
            returns the output between submission and prompt.
        - raw_send=True: pass a command. The text is written without
            waiting for prompt. Use for REPL input ("p('hi')\\n"), for
            password prompts (sudo), or for vim keystrokes.
        - read_only=True: drains whatever's currently buffered.
            Typically follows raw_send.

        Args:
            session_id: From shell_pty_open.
            command: The text to send. None when read_only=True.
            expect: Regex to wait for INSTEAD of the default prompt sentinel.
                Useful when the command launches a REPL with its own prompt.
            raw_send: Don't wait for prompt; just write.
            read_only: Don't send anything; drain the buffer.
            timeout_sec: Max wait. On timeout, returns whatever's buffered
                with timed_out=True (the command may still be running —
                check with another _run call).

        Returns: {output, prompt_after, timed_out, ...}
        """
        sess = _REGISTRY.get(session_id)
        if sess is None:
            return {"error": f"unknown session_id: {session_id}"}
        if not sess.is_alive():
            _REGISTRY.remove(session_id)
            return {"error": f"session {session_id} has exited"}

        if read_only:
            return sess.drain(timeout_sec=timeout_sec)

        if command is None:
            return {"error": "command is required unless read_only=True"}

        if raw_send:
            n = sess.send_raw(command, add_newline=False)
            return {"bytes_sent": n}

        try:
            return sess.run(command, expect=expect, timeout_sec=timeout_sec)
        except SessionBusy as e:
            return {"error": str(e)}

    @mcp.tool()
    def shell_pty_close(session_id: str, force: bool = False) -> dict:
        """Terminate a PTY session. Always do this when you're done — leaked
        sessions count against the per-server PTY cap.

        Args:
            session_id: From shell_pty_open.
            force: Skip the graceful "exit\\n" attempt and SIGTERM/SIGKILL.

        Returns: {exit_code, final_output, already_closed}
        """
        sess = _REGISTRY.get(session_id)
        if sess is None:
            return {"error": f"unknown session_id: {session_id}"}
        result = sess.close(force=force)
        _REGISTRY.remove(session_id)
        return result


__all__ = ["register_pty_tools", "get_registry"]
