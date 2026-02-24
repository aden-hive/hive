"""
GCU Browser Tool - Browser automation and interaction for GCU nodes.

Provides comprehensive browser automation capabilities:
- Browser lifecycle management (start/stop/status)
- Tab management (open/close/focus/list)
- Navigation and history
- Content extraction (screenshot, console, pdf)
- Element interaction (click, type, fill, etc.)
- Advanced operations (wait, evaluate, upload, dialog)
- Agent contexts (isolated sessions spawned from shared profiles)

Uses Playwright for browser automation.

Example usage:
    from fastmcp import FastMCP
    from gcu.browser import register_tools

    mcp = FastMCP("browser-agent")
    register_tools(mcp)
"""

from fastmcp import FastMCP

from .session import (
    DEFAULT_NAVIGATION_TIMEOUT_MS,
    DEFAULT_TIMEOUT_MS,
    BrowserSession,
    close_shared_browser,
    get_all_sessions,
    get_session,
    get_shared_browser,
)
from .tools import (
    register_advanced_tools,
    register_agent_tools,
    register_inspection_tools,
    register_interaction_tools,
    register_lifecycle_tools,
    register_navigation_tools,
    register_tab_tools,
)


def register_tools(mcp: FastMCP) -> None:
    """
    Register all GCU browser tools with the MCP server.

    Tools are organized into categories:
    - Lifecycle: browser_start, browser_stop, browser_status, browser_profiles
    - Tabs: browser_tabs, browser_open, browser_close, browser_focus
    - Navigation: browser_navigate, browser_go_back, browser_go_forward, browser_reload
    - Inspection: browser_screenshot, browser_console, browser_pdf
    - Interactions: browser_click, browser_type, browser_fill, browser_press,
                    browser_hover, browser_select, browser_scroll, browser_drag
    - Advanced: browser_wait, browser_evaluate, browser_get_text, browser_get_attribute,
                browser_resize, browser_upload, browser_dialog
    - Agents: browser_agent_create
    """
    register_lifecycle_tools(mcp)
    register_tab_tools(mcp)
    register_navigation_tools(mcp)
    register_inspection_tools(mcp)
    register_interaction_tools(mcp)
    register_advanced_tools(mcp)
    register_agent_tools(mcp)


__all__ = [
    # Main registration function
    "register_tools",
    # Session management (for advanced use cases)
    "BrowserSession",
    "get_session",
    "get_all_sessions",
    # Shared browser for agent contexts
    "get_shared_browser",
    "close_shared_browser",
    # Constants
    "DEFAULT_TIMEOUT_MS",
    "DEFAULT_NAVIGATION_TIMEOUT_MS",
]
