"""
Agent context tools - create isolated browser contexts from a shared profile.

Enables multiple agents to work concurrently, each with their own isolated
cookies/storage, all spawned from a running profile's state.
"""

from __future__ import annotations

from fastmcp import FastMCP

from ..session import BrowserSession, _sessions


def register_agent_tools(mcp: FastMCP) -> None:
    """Register agent context management tools."""

    @mcp.tool()
    async def browser_agent_create(
        agent_id: str,
        source_profile: str = "default",
        headless: bool = True,
    ) -> dict:
        """
        Create an isolated browser context for an agent from a running profile.

        Snapshots the source profile's current state (cookies, localStorage, etc.)
        and creates a new isolated context on a shared browser process. Each agent
        context is fully independent after creation — changes in one don't affect
        the others or the source profile.

        The source profile must be running (started via browser_start). After
        creation, use the agent_id as the profile parameter with all other
        browser_* tools.

        Args:
            agent_id: Unique name for this agent's context
            source_profile: Running profile to snapshot state from (default: "default")
            headless: Run the shared agent browser headless (default: True)

        Returns:
            Dict with agent context info. Use profile=agent_id with other tools.
        """
        if agent_id in _sessions and _sessions[agent_id]._is_running():
            return {
                "ok": True,
                "status": "already_exists",
                "profile": agent_id,
                "message": f"Agent context '{agent_id}' already exists. "
                f"Use profile='{agent_id}' with other browser tools.",
            }

        source = _sessions.get(source_profile)
        if not source or not source._is_running():
            return {
                "ok": False,
                "error": f"Source profile '{source_profile}' is not running. "
                f"Start it first with browser_start(profile='{source_profile}').",
            }

        try:
            session = await BrowserSession.create_agent_session(
                agent_id=agent_id,
                source_session=source,
                headless=headless,
            )
            _sessions[agent_id] = session
            return {
                "ok": True,
                "status": "created",
                "profile": agent_id,
                "source_profile": source_profile,
                "message": f"Agent context created. Use profile='{agent_id}' "
                "with all browser_* tools.",
            }
        except Exception as e:
            return {"ok": False, "error": f"Failed to create agent context: {e!s}"}
