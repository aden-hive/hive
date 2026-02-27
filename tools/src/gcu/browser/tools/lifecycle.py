"""
Browser lifecycle tools - start, stop, status.
"""

from fastmcp import FastMCP

from ..session import get_session


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
    ) -> dict:
        """
        Start the browser with a persistent profile.

        Browser data (cookies, localStorage, logins) persists at
        ~/.hive/agents/{agent}/browser/{profile}/
        A CDP debugging port is allocated in range 18800-18899.

        Args:
            profile: Browser profile name (default: "default")

        Returns:
            Dict with start status, including user_data_dir and cdp_port
        """
        session = get_session(profile)
        return await session.start(headless=False, persistent=True)

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
