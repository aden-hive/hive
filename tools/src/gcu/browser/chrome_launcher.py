"""
Launch and manage a system Chrome/Edge process for CDP connections.

Starts the browser as a subprocess with ``--remote-debugging-port`` and waits
until the CDP endpoint is ready.  Used by ``session.py`` to replace
Playwright's ``chromium.launch()`` with a system-installed browser.
"""

from __future__ import annotations

import asyncio
import logging
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
]

# Sandbox flags are only needed on Linux (Docker, CI). On macOS they
# trigger a yellow warning bar and serve no purpose.
if sys.platform == "linux":
    _CHROME_ARGS = ["--no-sandbox", "--disable-setuid-sandbox", *_CHROME_ARGS]

# CDP readiness polling
_CDP_POLL_INTERVAL_S = 0.1
_CDP_MAX_WAIT_S = 10.0


@dataclass
class ChromeProcess:
    """Handle to a running Chrome subprocess launched for CDP access."""

    process: subprocess.Popen[bytes]
    cdp_port: int
    cdp_url: str
    user_data_dir: Path
    _temp_dir: tempfile.TemporaryDirectory[str] | None = field(default=None, repr=False)

    def is_alive(self) -> bool:
        return self.process.poll() is None

    async def kill(self) -> None:
        """Terminate the Chrome process and clean up resources."""
        if self.process.poll() is None:
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

    from .session import _get_viewport

    vp = _get_viewport()
    args = [
        chrome_path,
        f"--remote-debugging-port={cdp_port}",
        f"--user-data-dir={user_data_dir}",
        f"--window-size={vp['width']},{vp['height']}",
        "--lang=en-US",
        *_CHROME_ARGS,
        *(extra_args or []),
    ]

    if headless:
        args.append("--headless=new")

    logger.info(f"Launching Chrome: port={cdp_port}, user_data_dir={user_data_dir}")

    process = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    cdp_url = f"http://127.0.0.1:{cdp_port}"

    # Wait for CDP to become ready
    try:
        await _wait_for_cdp(cdp_port, process)
    except Exception:
        # Clean up on failure
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
    process: subprocess.Popen[bytes],
    timeout: float = _CDP_MAX_WAIT_S,
) -> None:
    """Poll ``/json/version`` until Chrome's CDP endpoint is ready."""
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
        # Check the process hasn't crashed
        if process.poll() is not None:
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
