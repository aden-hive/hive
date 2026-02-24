"""
Browser lifecycle tools - start, stop, status, profiles.
"""

from fastmcp import FastMCP

from ..session import get_all_sessions, get_session


def register_lifecycle_tools(mcp: FastMCP) -> None:
    """Register browser lifecycle management tools."""

    @mcp.tool()
    async def browser_status(profile: str = "default") -> dict:
        """
        Get the current status of the browser.

        Args:
            profile: Browser profile name (default: "default")

        Returns:
            Dict with browser status (running, tabs count, active tab, persistent, cdp_port)
        """
        session = get_session(profile)
        return await session.status()

    @mcp.tool()
    async def browser_start(
        profile: str = "default",
        headless: bool = False,
        persistent: bool = True,
    ) -> dict:
        """
        Start the browser.

        Args:
            profile: Browser profile name (default: "default")
            headless: Run browser in headless mode (default: False)
            persistent: Use persistent profile for cookies/storage (default: True)
                When True, browser data persists at ~/.hive/agents/{agent}/browser/{profile}/
                CDP debugging port allocated in range 18800-18899

        Returns:
            Dict with start status, including user_data_dir and cdp_port when persistent
        """
        session = get_session(profile)
        return await session.start(headless=headless, persistent=persistent)

    @mcp.tool()
    async def browser_stop(profile: str = "default") -> dict:
        """
        Stop the browser and close all tabs.

        Args:
            profile: Browser profile name (default: "default")

        Returns:
            Dict with stop status
        """
        session = get_session(profile)
        return await session.stop()

    @mcp.tool()
    async def browser_profiles() -> dict:
        """
        List all available browser profiles.

        Returns:
            Dict with list of profile names and their status
        """
        profiles = []
        for name, session in get_all_sessions().items():
            status = await session.status()
            profiles.append(
                {
                    "name": name,
                    "running": status.get("running", False),
                    "tabs": status.get("tabs", 0),
                }
            )
        # Always include default if not present
        if "default" not in get_all_sessions():
            profiles.append({"name": "default", "running": False, "tabs": 0})
        return {"ok": True, "profiles": profiles}
