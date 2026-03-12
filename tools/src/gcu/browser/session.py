"""
Browser session management.

Connects to system-installed Chrome/Edge via CDP for browser automation.
Each session launches a Chrome subprocess with ``--remote-debugging-port``
and connects Playwright as a CDP client.

Supports three session types:
- Standard: Single browser with ephemeral or persistent context
- Agent: Isolated context spawned from a running profile's state,
  sharing a single browser process with other agent sessions
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    async_playwright,
)

logger = logging.getLogger(__name__)

# Browser User-Agent for stealth mode
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Stealth script to hide automation detection
# Injected via add_init_script() to run before any page scripts
STEALTH_SCRIPT = """
// Override navigator.webdriver to return false
Object.defineProperty(navigator, 'webdriver', {
    get: () => false,
    configurable: true
});

// Remove webdriver from navigator prototype
delete Object.getPrototypeOf(navigator).webdriver;

// Override permissions.query to hide automation
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);

// Hide Chrome automation extensions
if (window.chrome) {
    window.chrome.runtime = undefined;
}

// Override plugins to look more realistic
Object.defineProperty(navigator, 'plugins', {
    get: () => [
        { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
        { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
        { name: 'Native Client', filename: 'internal-nacl-plugin' }
    ],
    configurable: true
});

// Override languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
    configurable: true
});
"""

# Branded start page HTML with Hive theme
HIVE_START_PAGE = """
<!DOCTYPE html>
<html>
<head>
    <title>Hive Browser</title>
    <style>
        :root {
            --primary: #FAC43B;
            --bg: #1a1a1a;
            --text: #ffffff;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg);
            color: var(--text);
            height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
        }
        .logo {
            width: 80px;
            height: 80px;
            background: var(--primary);
            border-radius: 16px;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 24px;
            font-size: 40px;
        }
        h1 {
            font-size: 28px;
            font-weight: 600;
            margin-bottom: 8px;
            color: var(--primary);
        }
        p {
            color: #888;
            font-size: 14px;
        }
        .status {
            position: fixed;
            bottom: 20px;
            display: flex;
            align-items: center;
            gap: 8px;
            color: #666;
            font-size: 12px;
        }
        .dot {
            width: 8px;
            height: 8px;
            background: #4ade80;
            border-radius: 50%;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
    </style>
</head>
<body>
    <div class="logo">🐝</div>
    <h1>Hive Browser</h1>
    <p>Ready for automation</p>
    <div class="status">
        <span class="dot"></span>
        <span>Agent connected</span>
    </div>
</body>
</html>
"""

# Default timeouts
DEFAULT_TIMEOUT_MS = 30000
DEFAULT_NAVIGATION_TIMEOUT_MS = 60000

# Valid wait_until values for Playwright navigation
VALID_WAIT_UNTIL = {"commit", "domcontentloaded", "load", "networkidle"}

# ---------------------------------------------------------------------------
# Shared browser for agent contexts
# ---------------------------------------------------------------------------
# All agent sessions share this single Chrome process + CDP connection.
# We can call browser.new_context() multiple times with different storage states.

_shared_browser: Browser | None = None
_shared_playwright: Any = None
_shared_chrome_process: Any = None  # ChromeProcess | None (avoid circular import)
_shared_cdp_port: int | None = None

# ---------------------------------------------------------------------------
# Dynamic viewport sizing
# ---------------------------------------------------------------------------

DEFAULT_VIEWPORT_SCALE = 0.8
_FALLBACK_WIDTH = 1920
_FALLBACK_HEIGHT = 1080


def _detect_screen_resolution() -> tuple[int, int] | None:
    """Detect primary monitor resolution using platform-native tools.

    Returns (width, height) or None if detection fails (headless, no display).
    """
    if sys.platform == "darwin":
        try:
            import subprocess

            out = subprocess.check_output(
                ["system_profiler", "SPDisplaysDataType"],
                text=True,
                timeout=5,
            )
            import re

            match = re.search(r"Resolution:\s+(\d+)\s*x\s*(\d+)", out)
            if match:
                return int(match.group(1)), int(match.group(2))
        except Exception:
            pass
    elif sys.platform == "win32":
        try:
            import ctypes

            user32 = ctypes.windll.user32
            return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        except Exception:
            pass
    else:
        # Linux — try xrandr
        try:
            import subprocess

            out = subprocess.check_output(
                ["xrandr", "--current"],
                text=True,
                timeout=5,
            )
            import re

            match = re.search(r"(\d+)x(\d+)\s+\d+\.\d+\*", out)
            if match:
                return int(match.group(1)), int(match.group(2))
        except Exception:
            pass
    return None


def _get_viewport(scale: float | None = None) -> dict[str, int]:
    """Compute viewport as a percentage of the primary monitor resolution.

    Falls back to 1920x1080 if screen detection fails (e.g. headless server).
    Scale priority: explicit arg > env var > config file > default (0.8).
    """
    if scale is None:
        env_scale = os.environ.get("HIVE_BROWSER_VIEWPORT_SCALE")
        if env_scale:
            try:
                scale = float(env_scale)
            except ValueError:
                logger.warning("Invalid HIVE_BROWSER_VIEWPORT_SCALE=%r, using default", env_scale)
    if scale is None:
        try:
            from framework.config import get_gcu_viewport_scale

            scale = get_gcu_viewport_scale()
        except ImportError:
            scale = DEFAULT_VIEWPORT_SCALE
    scale = max(0.1, min(1.0, scale))

    resolution = _detect_screen_resolution()
    if resolution:
        w, h = resolution
        logger.debug("Detected screen resolution: %dx%d", w, h)
    else:
        w, h = _FALLBACK_WIDTH, _FALLBACK_HEIGHT
        logger.debug("Could not detect screen resolution, using default %dx%d", w, h)

    return {"width": int(w * scale), "height": int(h * scale)}


async def get_shared_browser(headless: bool = True) -> Browser:
    """Get or create the shared browser instance for agent contexts."""
    global _shared_browser, _shared_playwright, _shared_chrome_process, _shared_cdp_port

    if _shared_browser and _shared_browser.is_connected():
        return _shared_browser

    from .chrome_launcher import launch_chrome
    from .port_manager import allocate_port

    cdp_port = allocate_port("__shared__")
    _shared_cdp_port = cdp_port
    _shared_chrome_process = await launch_chrome(
        cdp_port=cdp_port,
        user_data_dir=None,  # ephemeral
        headless=headless,
    )
    _shared_playwright = await async_playwright().start()
    _shared_browser = await _shared_playwright.chromium.connect_over_cdp(
        _shared_chrome_process.cdp_url
    )
    logger.info("Started shared browser for agent contexts (system Chrome)")
    return _shared_browser


async def close_shared_browser() -> None:
    """Close the shared browser and clean up all agent contexts."""
    global _shared_browser, _shared_playwright, _shared_chrome_process, _shared_cdp_port

    if _shared_browser:
        await _shared_browser.close()
        _shared_browser = None
        logger.info("Closed shared browser")

    if _shared_playwright:
        await _shared_playwright.stop()
        _shared_playwright = None

    if _shared_chrome_process:
        await _shared_chrome_process.kill()
        _shared_chrome_process = None

    if _shared_cdp_port is not None:
        from .port_manager import release_port

        release_port(_shared_cdp_port)
        _shared_cdp_port = None


@dataclass
class BrowserSession:
    """
    Manages a browser session with multiple tabs.

    Each session corresponds to a profile and maintains:
    - A single browser instance (or persistent context)
    - A browser context with shared cookies/storage
    - Multiple pages (tabs)
    - Console message capture per tab

    When persistent=True, the browser profile is stored at:
    ~/.hive/agents/{agent_name}/browser/{profile}/
    """

    profile: str
    browser: Browser | None = None
    context: BrowserContext | None = None
    pages: dict[str, Page] = field(default_factory=dict)
    active_page_id: str | None = None
    console_messages: dict[str, list[dict]] = field(default_factory=dict)
    _playwright: Any = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # Persistent profile fields
    persistent: bool = False
    user_data_dir: Path | None = None
    cdp_port: int | None = None

    # Session type: "standard" (default) or "agent" (ephemeral context from shared browser)
    session_type: str = "standard"

    # Chrome subprocess handle (standard sessions only)
    _chrome_process: Any = None  # ChromeProcess | None

    def _is_running(self) -> bool:
        """Check if browser is currently running."""
        if self.session_type == "agent":
            # Agent sessions use a shared browser; check context is alive
            return (
                self.context is not None
                and self.browser is not None
                and self.browser.is_connected()
            )
        # Both persistent and ephemeral now have a browser object via CDP
        return self.browser is not None and self.browser.is_connected()

    async def _health_check(self) -> None:
        """Verify the browser is responsive by evaluating JS on a page.

        Uses an existing page if available (persistent contexts always have at
        least one), otherwise creates and closes a temporary page.

        Raises:
            RuntimeError: If the browser doesn't respond to JS evaluation.
        """
        page = None
        temp = False
        if self.context.pages:
            page = self.context.pages[0]
        else:
            page = await self.context.new_page()
            temp = True
        try:
            result = await page.evaluate("document.readyState")
            if result not in ("loading", "interactive", "complete"):
                raise RuntimeError(f"Unexpected readyState: {result}")
        finally:
            if temp:
                await page.close()

    async def _cleanup_after_failed_start(self) -> None:
        """Release resources after a health-check failure inside start().

        We're already inside ``self._lock`` so we can't call ``stop()``.
        This mirrors the teardown logic without re-acquiring the lock.
        """
        if self.cdp_port:
            from .port_manager import release_port

            release_port(self.cdp_port)
            self.cdp_port = None

        if self.context:
            try:
                await self.context.close()
            except Exception:
                pass
            self.context = None

        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
            self.browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        if self._chrome_process:
            try:
                await self._chrome_process.kill()
            except Exception:
                pass
            self._chrome_process = None

        self.pages.clear()
        self.active_page_id = None
        self.console_messages.clear()

    async def start(self, headless: bool = True, persistent: bool = True) -> dict:
        """
        Start the browser.

        Args:
            headless: Run browser in headless mode (default: True)
            persistent: Use persistent profile for cookies/storage (default: True)
                When True, browser data persists at ~/.hive/agents/{agent}/browser/{profile}/

        Returns:
            Dict with start status, including user_data_dir and cdp_port when persistent
        """
        async with self._lock:
            if self._is_running():
                return {
                    "ok": True,
                    "status": "already_running",
                    "profile": self.profile,
                    "persistent": self.persistent,
                    "user_data_dir": str(self.user_data_dir) if self.user_data_dir else None,
                    "cdp_port": self.cdp_port,
                }

            from .chrome_launcher import launch_chrome
            from .port_manager import allocate_port

            self._playwright = await async_playwright().start()
            self.persistent = persistent

            if persistent:
                # Get storage path from environment (set by AgentRunner)
                storage_path_str = os.environ.get("HIVE_STORAGE_PATH")
                agent_name = os.environ.get("HIVE_AGENT_NAME", "default")

                if storage_path_str:
                    self.user_data_dir = Path(storage_path_str) / "browser" / self.profile
                else:
                    # Fallback to ~/.hive/agents/{agent}/browser/{profile}
                    self.user_data_dir = (
                        Path.home() / ".hive" / "agents" / agent_name / "browser" / self.profile
                    )

                self.user_data_dir.mkdir(parents=True, exist_ok=True)
            else:
                self.user_data_dir = None  # chrome_launcher creates a temp dir

            # Allocate CDP port for system Chrome
            self.cdp_port = allocate_port(self.profile)

            logger.info(
                f"Starting {'persistent' if persistent else 'ephemeral'} browser: "
                f"profile={self.profile}, user_data_dir={self.user_data_dir}, "
                f"cdp_port={self.cdp_port}"
            )

            # Launch system Chrome and connect via CDP
            self._chrome_process = await launch_chrome(
                cdp_port=self.cdp_port,
                user_data_dir=self.user_data_dir,
                headless=headless,
                extra_args=[f"--user-agent={BROWSER_USER_AGENT}"],
            )
            self.browser = await self._playwright.chromium.connect_over_cdp(
                self._chrome_process.cdp_url
            )
            self.context = self.browser.contexts[0]

            # Inject stealth script to hide automation detection
            await self.context.add_init_script(STEALTH_SCRIPT)

            # Set viewport on existing pages (CDP default context doesn't
            # inherit viewport settings like launch_persistent_context did)
            viewport = _get_viewport()
            for page in self.context.pages:
                await page.set_viewport_size(viewport)

            if persistent:
                # Register existing pages from restored session
                for page in self.context.pages:
                    target_id = f"tab_{id(page)}"
                    self.pages[target_id] = page
                    self.console_messages[target_id] = []
                    page.on("console", lambda msg, tid=target_id: self._capture_console(tid, msg))
                    if self.active_page_id is None:
                        self.active_page_id = target_id

                # Set branded Hive start page on the first blank page
                if self.context.pages:
                    first_page = self.context.pages[0]
                    url = first_page.url
                    # Only set branded content if it's a blank/new tab page
                    if url in ("", "about:blank", "chrome://newtab/"):
                        await first_page.set_content(HIVE_START_PAGE)

            # Health check: confirm the browser is actually responsive
            try:
                await self._health_check()
            except Exception as exc:
                logger.error(f"Browser health check failed: {exc}")
                await self._cleanup_after_failed_start()
                return {
                    "ok": False,
                    "error": f"Browser started but health check failed: {exc}",
                }

            return {
                "ok": True,
                "status": "started",
                "profile": self.profile,
                "persistent": self.persistent,
                "user_data_dir": str(self.user_data_dir) if self.user_data_dir else None,
                "cdp_port": self.cdp_port,
            }

    async def stop(self) -> dict:
        """Stop the browser and clean up resources."""
        async with self._lock:
            # Release CDP port if allocated
            if self.cdp_port:
                from .port_manager import release_port

                release_port(self.cdp_port)
                self.cdp_port = None

            # Close context (works for both persistent and ephemeral)
            if self.context:
                await self.context.close()
                self.context = None

            # Agent sessions share a browser — don't close it (other agents depend on it).
            # Only standard sessions own their browser and playwright instances.
            if self.session_type != "agent":
                if self.browser:
                    await self.browser.close()
                    self.browser = None

                if self._playwright:
                    await self._playwright.stop()
                    self._playwright = None

                # Kill the Chrome subprocess
                if self._chrome_process:
                    await self._chrome_process.kill()
                    self._chrome_process = None
            else:
                self.browser = None  # Drop reference to shared browser

            self.pages.clear()
            self.active_page_id = None
            self.console_messages.clear()
            self.user_data_dir = None
            self.persistent = False

            return {"ok": True, "status": "stopped", "profile": self.profile}

    @staticmethod
    async def create_agent_session(
        agent_id: str,
        source_session: BrowserSession,
        headless: bool = True,
    ) -> BrowserSession:
        """
        Create an agent session by snapshotting a running profile's state.

        Takes the source session's current cookies/localStorage via storageState
        and stamps them into a new isolated context on the shared browser.
        Each agent context is fully independent after creation.

        Args:
            agent_id: Unique name for this agent's session
            source_session: Running session to snapshot state from
            headless: Run shared browser headless (default: True)
        """
        if not source_session.context:
            raise RuntimeError(
                f"Source profile '{source_session.profile}' has no active context. "
                f"Start it first with browser_start."
            )

        # Snapshot the source profile's cookies + localStorage in memory
        storage_state = await source_session.context.storage_state()

        # Get the shared browser (creates it on first call)
        browser = await get_shared_browser(headless=headless)

        # Create an isolated context stamped with the snapshot
        context = await browser.new_context(
            storage_state=storage_state,
            viewport=_get_viewport(),
            user_agent=BROWSER_USER_AGENT,
            locale="en-US",
        )
        await context.add_init_script(STEALTH_SCRIPT)

        session = BrowserSession(
            profile=agent_id,
            browser=browser,
            context=context,
            session_type="agent",
        )
        logger.info(f"Created agent session '{agent_id}' from profile '{source_session.profile}'")
        return session

    async def status(self) -> dict:
        """Get browser status."""
        return {
            "ok": True,
            "profile": self.profile,
            "session_type": self.session_type,
            "running": self._is_running(),
            "persistent": self.persistent,
            "user_data_dir": str(self.user_data_dir) if self.user_data_dir else None,
            "cdp_port": self.cdp_port,
            "tabs": len(self.pages),
            "active_tab": self.active_page_id,
        }

    async def ensure_running(self) -> None:
        """Ensure browser is running, starting it if necessary."""
        if not self._is_running():
            await self.start(persistent=self.persistent)

    async def open_tab(self, url: str, background: bool = False, wait_until: str = "load") -> dict:
        """Open a new tab with the given URL.

        Args:
            url: URL to navigate to.
            background: If True, open the tab via CDP Target.createTarget with
                background=True so it does not steal focus from the current tab.
            wait_until: When to consider navigation complete. One of
                ``"commit"``, ``"domcontentloaded"``, ``"load"`` (default),
                ``"networkidle"``.
        """
        if wait_until not in VALID_WAIT_UNTIL:
            raise ValueError(
                f"Invalid wait_until={wait_until!r}. "
                f"Must be one of: {', '.join(sorted(VALID_WAIT_UNTIL))}"
            )

        await self.ensure_running()
        if not self.context:
            raise RuntimeError("Browser context not initialized")

        if background:
            return await self._open_tab_background(url, wait_until=wait_until)

        page = await self.context.new_page()
        target_id = f"tab_{id(page)}"
        self.pages[target_id] = page
        self.active_page_id = target_id
        self.console_messages[target_id] = []

        # Set up console message capture
        page.on("console", lambda msg: self._capture_console(target_id, msg))

        await page.goto(url, wait_until=wait_until, timeout=DEFAULT_NAVIGATION_TIMEOUT_MS)

        return {
            "ok": True,
            "targetId": target_id,
            "url": page.url,
            "title": await page.title(),
        }

    async def _open_tab_background(self, url: str, wait_until: str = "load") -> dict:
        """Open a tab in the background using CDP Target.createTarget.

        Uses CDP to create the target with background=True so the current
        active tab keeps focus, then picks up the new page via Playwright's
        context page event.
        """
        # Need an existing page to create a CDP session from
        anchor_page = self.get_active_page()
        if not anchor_page and self.context.pages:
            anchor_page = self.context.pages[0]
        if not anchor_page:
            # Nothing to steal focus from — just open normally
            page = await self.context.new_page()
            target_id = f"tab_{id(page)}"
            self.pages[target_id] = page
            self.active_page_id = target_id
            self.console_messages[target_id] = []
            page.on("console", lambda msg: self._capture_console(target_id, msg))
            await page.goto(url, wait_until=wait_until, timeout=DEFAULT_NAVIGATION_TIMEOUT_MS)
            return {
                "ok": True,
                "targetId": target_id,
                "url": page.url,
                "title": await page.title(),
                "background": False,
            }

        cdp = await self.context.new_cdp_session(anchor_page)
        try:
            # Get the browserContextId so the new tab lands in the same context
            target_info = await cdp.send("Target.getTargetInfo")
            browser_context_id = target_info.get("targetInfo", {}).get("browserContextId")

            # Listen for the new page before creating it
            page_promise = asyncio.ensure_future(
                self.context.wait_for_event("page", timeout=DEFAULT_NAVIGATION_TIMEOUT_MS)
            )

            create_params: dict[str, Any] = {"url": url, "background": True}
            if browser_context_id:
                create_params["browserContextId"] = browser_context_id

            await cdp.send("Target.createTarget", create_params)

            # Playwright picks up the new target automatically
            page = await page_promise
            await page.wait_for_load_state(wait_until, timeout=DEFAULT_NAVIGATION_TIMEOUT_MS)
        finally:
            await cdp.detach()

        target_id = f"tab_{id(page)}"
        self.pages[target_id] = page
        # Don't update active_page_id — the whole point is to stay on the current tab
        self.console_messages[target_id] = []
        page.on("console", lambda msg: self._capture_console(target_id, msg))

        return {
            "ok": True,
            "targetId": target_id,
            "url": page.url,
            "title": await page.title(),
            "background": True,
        }

    def _capture_console(self, target_id: str, msg: Any) -> None:
        """Capture console messages for a tab."""
        if target_id in self.console_messages:
            self.console_messages[target_id].append(
                {
                    "type": msg.type,
                    "text": msg.text,
                }
            )

    async def close_tab(self, target_id: str | None = None) -> dict:
        """Close a tab."""
        tid = target_id or self.active_page_id
        if not tid or tid not in self.pages:
            return {"ok": False, "error": "Tab not found"}

        page = self.pages.pop(tid)
        await page.close()
        self.console_messages.pop(tid, None)

        if self.active_page_id == tid:
            self.active_page_id = next(iter(self.pages), None)

        return {"ok": True, "closed": tid}

    async def focus_tab(self, target_id: str) -> dict:
        """Focus a tab by bringing it to front."""
        if target_id not in self.pages:
            return {"ok": False, "error": "Tab not found"}

        self.active_page_id = target_id
        await self.pages[target_id].bring_to_front()
        return {"ok": True, "targetId": target_id}

    async def list_tabs(self) -> list[dict]:
        """List all open tabs with their metadata."""
        tabs = []
        for tid, page in self.pages.items():
            try:
                tabs.append(
                    {
                        "targetId": tid,
                        "url": page.url,
                        "title": await page.title(),
                        "active": tid == self.active_page_id,
                    }
                )
            except Exception:
                pass
        return tabs

    def get_active_page(self) -> Page | None:
        """Get the currently active page."""
        if self.active_page_id and self.active_page_id in self.pages:
            return self.pages[self.active_page_id]
        return None

    def get_page(self, target_id: str | None = None) -> Page | None:
        """Get a page by target_id or return the active page."""
        if target_id:
            return self.pages.get(target_id)
        return self.get_active_page()


# ---------------------------------------------------------------------------
# Global Session Registry
# ---------------------------------------------------------------------------

_sessions: dict[str, BrowserSession] = {}


def get_session(profile: str = "default") -> BrowserSession:
    """Get or create a browser session for a profile."""
    if profile not in _sessions:
        _sessions[profile] = BrowserSession(profile=profile)
    return _sessions[profile]


def get_all_sessions() -> dict[str, BrowserSession]:
    """Get all registered sessions."""
    return _sessions
