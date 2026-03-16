"""
Launch and manage a system Chrome/Edge process for CDP connections.

Starts the browser as a subprocess with ``--remote-debugging-port`` and waits
until the CDP endpoint is ready.  Used by ``session.py`` to replace
Playwright's ``chromium.launch()`` with a system-installed browser.

On macOS, uses ``open -n -a`` to force a new Chrome instance even when the
user's personal Chrome is already running.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from .chrome_finder import require_chrome

logger = logging.getLogger(__name__)

# Chrome flags for all browser launches
_CHROME_ARGS = [
    "--disable-dev-shm-usage",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-session-crashed-bubble",
    "--noerrdialogs",
    "--no-startup-window",
]

# Sandbox flags are only needed on Linux (Docker, CI). On macOS they
# trigger a yellow warning bar and serve no purpose.
if sys.platform == "linux":
    _CHROME_ARGS = ["--no-sandbox", "--disable-setuid-sandbox", *_CHROME_ARGS]

# CDP readiness polling
_CDP_POLL_INTERVAL_S = 0.1
_CDP_MAX_WAIT_S = 10.0


def _clear_session_restore(user_data_dir: Path) -> None:
    """Remove Chrome session restore files to prevent tab/window restoration.

    Cookies and localStorage are stored separately and are unaffected.
    """
    default_dir = user_data_dir / "Default"
    for name in ("Current Session", "Current Tabs", "Last Session", "Last Tabs"):
        target = default_dir / name
        if target.exists():
            try:
                target.unlink()
                logger.debug("Removed session restore file: %s", target)
            except OSError:
                pass


def _resolve_app_bundle(executable_path: str) -> str | None:
    """Extract .app bundle path from a macOS executable path.

    e.g. '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
      -> '/Applications/Google Chrome.app'
    """
    parts = Path(executable_path).parts
    for i, part in enumerate(parts):
        if part.endswith(".app"):
            return str(Path(*parts[: i + 1]))
    return None


def _find_pid_on_port(port: int) -> int | None:
    """Find the PID listening on a TCP port via lsof."""
    try:
        output = subprocess.check_output(
            ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
            text=True,
            timeout=5,
        ).strip()
        pids = [int(p) for p in output.split("\n") if p.strip()]
        return pids[0] if pids else None
    except Exception:
        return None


def _kill_chrome_by_data_dir(user_data_dir: Path) -> None:
    """Find and kill a Chrome process by its --user-data-dir argument.

    Fallback for when Chrome started but never bound the CDP port,
    so _find_pid_on_port cannot locate it.
    """
    try:
        # pgrep -f matches against the full command line
        output = subprocess.check_output(
            ["pgrep", "-f", f"--user-data-dir={user_data_dir}"],
            text=True,
            timeout=5,
        ).strip()
        for pid_str in output.split("\n"):
            pid_str = pid_str.strip()
            if pid_str:
                try:
                    pid = int(pid_str)
                    os.kill(pid, signal.SIGKILL)
                    logger.info(f"Killed orphaned Chrome pid={pid} (matched user-data-dir)")
                except (ValueError, OSError):
                    pass
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        pass  # No matching process found


@dataclass
class ChromeProcess:
    """Handle to a running Chrome process launched for CDP access."""

    process: subprocess.Popen[bytes] | None  # None when launched via open -n (macOS)
    cdp_port: int
    cdp_url: str
    user_data_dir: Path
    _temp_dir: tempfile.TemporaryDirectory[str] | None = field(default=None, repr=False)
    _pid: int | None = field(default=None, repr=False)

    def is_alive(self) -> bool:
        if self.process is not None:
            return self.process.poll() is None
        if self._pid is not None:
            try:
                os.kill(self._pid, 0)
                return True
            except OSError:
                return False
        return False

    async def kill(self) -> None:
        """Terminate the Chrome process and clean up resources."""
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, self.process.wait),
                    timeout=5.0,
                )
            except TimeoutError:
                self.process.kill()
                self.process.wait()
            logger.info(f"Chrome process (port {self.cdp_port}) terminated")
        elif self._pid is not None:
            try:
                os.kill(self._pid, signal.SIGTERM)
                # Wait briefly for graceful shutdown
                loop = asyncio.get_event_loop()
                for _ in range(50):  # 5 seconds max
                    alive = await loop.run_in_executor(None, self.is_alive)
                    if not alive:
                        break
                    await asyncio.sleep(0.1)
                else:
                    os.kill(self._pid, signal.SIGKILL)
                logger.info(f"Chrome process pid={self._pid} (port {self.cdp_port}) terminated")
            except OSError:
                pass
            self._pid = None

        # Clean up temp directory for ephemeral sessions
        if self._temp_dir is not None:
            try:
                self._temp_dir.cleanup()
            except Exception:
                pass
            self._temp_dir = None


async def launch_chrome(
    cdp_port: int,
    user_data_dir: Path | None = None,
    headless: bool = True,
    extra_args: list[str] | None = None,
) -> ChromeProcess:
    """Launch system Chrome and wait for CDP to become ready.

    Args:
        cdp_port: Port for ``--remote-debugging-port``.
        user_data_dir: Profile directory. If *None*, a temporary directory is
            created and cleaned up when the process is killed (ephemeral mode).
        headless: Use Chrome's headless mode (``--headless=new``).
        extra_args: Additional Chrome CLI flags.

    Returns:
        A :class:`ChromeProcess` handle.

    Raises:
        RuntimeError: If Chrome is not found, fails to start, or CDP does not
            become ready within the timeout.
    """
    chrome_path = require_chrome()

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if user_data_dir is None:
        temp_dir = tempfile.TemporaryDirectory(prefix="hive-browser-")
        user_data_dir = Path(temp_dir.name)

    _clear_session_restore(user_data_dir)

    from .session import _get_viewport

    vp = _get_viewport()
    chrome_flags = [
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={user_data_dir}",
        f"--window-size={vp['width']},{vp['height']}",
        "--lang=en-US",
        *_CHROME_ARGS,
        *(extra_args or []),
    ]

    if headless:
        chrome_flags.append("--headless=new")

    # Don't pass a URL arg — let Chrome open its default page.
    # session.py will close all initial pages and create a clean one.
    # Passing "about:blank" caused macOS to show a visible blank tab
    # that the CDP connection couldn't control, blocking the session.

    cdp_url = f"http://127.0.0.1:{cdp_port}"

    # On macOS, use `open -n -a` to force a new Chrome instance even when the
    # user's personal Chrome is already running. Chrome's Mach-based IPC would
    # otherwise delegate to the existing instance and exit with code 0.
    if sys.platform == "darwin":
        app_bundle = _resolve_app_bundle(chrome_path)
        if app_bundle:
            return await _launch_chrome_macos(
                app_bundle, chrome_flags, cdp_port, cdp_url, user_data_dir, temp_dir
            )

    # Linux, Windows, or macOS fallback (no .app bundle found)
    return await _launch_chrome_subprocess(
        chrome_path, chrome_flags, cdp_port, cdp_url, user_data_dir, temp_dir
    )


async def _launch_chrome_macos(
    app_bundle: str,
    chrome_flags: list[str],
    cdp_port: int,
    cdp_url: str,
    user_data_dir: Path,
    temp_dir: tempfile.TemporaryDirectory[str] | None,
) -> ChromeProcess:
    """Launch Chrome on macOS using ``open -n -a`` to bypass single-instance IPC."""
    logger.info(
        f"Launching Chrome (macOS open -n): app={app_bundle}, port={cdp_port}, "
        f"user_data_dir={user_data_dir}"
    )

    # `open -n` forces a new instance; --args passes flags to Chrome
    subprocess.Popen(
        ["open", "-n", "-a", app_bundle, "--args", *chrome_flags],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # `open` returns immediately — Chrome is now a child of launchd, not us.

    try:
        await _wait_for_cdp(cdp_port)
    except Exception:
        # Chrome may have started but not yet bound the CDP port.
        # Poll briefly to find and kill the orphaned process so it
        # doesn't hold the profile lock and block future launches.
        killed = False
        for _ in range(30):  # up to 3 seconds
            pid = _find_pid_on_port(cdp_port)
            if pid:
                try:
                    os.kill(pid, signal.SIGKILL)
                    killed = True
                    logger.info(f"Killed orphaned Chrome pid={pid} on port {cdp_port}")
                except OSError:
                    pass
                break
            time.sleep(0.1)
        if not killed:
            # Last resort: find Chrome by user-data-dir in process list
            _kill_chrome_by_data_dir(user_data_dir)
        if temp_dir is not None:
            temp_dir.cleanup()
        raise

    # Discover the Chrome PID listening on the CDP port
    pid = _find_pid_on_port(cdp_port)
    if pid is None:
        logger.warning(f"CDP ready on port {cdp_port} but could not discover Chrome PID")

    return ChromeProcess(
        process=None,
        cdp_port=cdp_port,
        cdp_url=cdp_url,
        user_data_dir=user_data_dir,
        _temp_dir=temp_dir,
        _pid=pid,
    )


async def _launch_chrome_subprocess(
    chrome_path: str,
    chrome_flags: list[str],
    cdp_port: int,
    cdp_url: str,
    user_data_dir: Path,
    temp_dir: tempfile.TemporaryDirectory[str] | None,
) -> ChromeProcess:
    """Launch Chrome as a direct subprocess (Linux, Windows, macOS fallback)."""
    args = [chrome_path, *chrome_flags]

    logger.info(f"Launching Chrome: port={cdp_port}, user_data_dir={user_data_dir}")

    process = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    try:
        await _wait_for_cdp(cdp_port, process=process)
    except Exception:
        process.kill()
        process.wait()
        if temp_dir is not None:
            temp_dir.cleanup()
        raise

    return ChromeProcess(
        process=process,
        cdp_port=cdp_port,
        cdp_url=cdp_url,
        user_data_dir=user_data_dir,
        _temp_dir=temp_dir,
    )


async def _wait_for_cdp(
    port: int,
    process: subprocess.Popen[bytes] | None = None,
    timeout: float = _CDP_MAX_WAIT_S,
) -> None:
    """Poll ``/json/version`` until Chrome's CDP endpoint is ready.

    When *process* is provided, also checks that the subprocess hasn't exited.
    When *process* is None (macOS ``open -n`` path), only polls the endpoint.
    """
    import urllib.error
    import urllib.request

    url = f"http://127.0.0.1:{port}/json/version"
    deadline = time.monotonic() + timeout

    def _probe() -> bool:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=1) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError, ConnectionError):
            return False

    while time.monotonic() < deadline:
        # Check the subprocess hasn't crashed (only when we have a handle)
        if process is not None and process.poll() is not None:
            stderr = ""
            if process.stderr:
                stderr = process.stderr.read().decode(errors="replace")
            raise RuntimeError(
                f"Chrome exited with code {process.returncode} before CDP "
                f"was ready.\nstderr: {stderr[:500]}"
            )

        try:
            loop = asyncio.get_running_loop()
            ready = await asyncio.wait_for(
                loop.run_in_executor(None, _probe),
                timeout=2.0,
            )
            if ready:
                elapsed = timeout - (deadline - time.monotonic())
                logger.info(f"CDP ready on port {port} after {elapsed:.1f}s")
                return
        except TimeoutError:
            pass

        await asyncio.sleep(_CDP_POLL_INTERVAL_S)

    raise RuntimeError(f"Chrome CDP endpoint did not become ready within {timeout}s on port {port}")
