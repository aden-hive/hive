"""
GCU Browser Tool - Browser automation via Beeline Chrome extension.

Control the user's browser directly via CDP - no Playwright required.
The user's Chrome will be visible in a new tab group
labeled with the agent ID. All interactions happen via CDP commands through
extension, using the user's cookies and login state.

Key benefits:
- Uses user's existing Chrome (LinkedIn, Gmail, etc. stay logged in)
- No separate headless browser process
- Faster - direct CDP, no context switching overhead
- Better debugging - browser is visible and inspectable
"""

from fastmcp import FastMCP

from .bridge import get_bridge, init_bridge
from .session import (
    BrowserSession,
    get_all_sessions,
    get_session,
    set_active_profile,
    shutdown_all_browsers,
)
from .tools import (
    register_advanced_tools,
    register_inspection_tools,
    register_interaction_tools,
    register_lifecycle_tools,
    register_navigation_tools,
    register_tab_tools,
)

# Constants
DEFAULT_TIMEOUT_MS = 30000
DEFAULT_NAVIGATION_TIMEOUT_MS = 60000


def register_tools(mcp: FastMCP) -> None:
    """Register all GCU browser tools with the MCP server.

    Tools are organized into categories:
    - Lifecycle: browser_start, browser_stop, browser_status
    - Tabs: browser_tabs, browser_open, browser_close, browser_focus
    - Navigation: browser_navigate, browser_go_back, browser_go_forward, browser_reload
    - Inspection: browser_screenshot, browser_snapshot, browser_console
    - Interactions: browser_click, browser_click_coordinate, browser_type, browser_type_focused,
                    browser_fill, browser_press, browser_hover, browser_select, browser_scroll, browser_drag
    - Advanced: browser_wait, browser_evaluate, browser_get_text, browser_get_attribute,
                  browser_resize, browser_upload, browser_dialog
    """
    register_lifecycle_tools(mcp)
    register_tab_tools(mcp)
    register_navigation_tools(mcp)
    register_inspection_tools(mcp)
    register_interaction_tools(mcp)
    register_advanced_tools(mcp)


__all__ = [
    # Main registration function
    "register_tools",
    # Bridge management
    "get_bridge",
    "init_bridge",
    # Session management
    "BrowserSession",
    "get_session",
    "get_all_sessions",
    "set_active_profile",
    "shutdown_all_browsers",
    # Constants
    "DEFAULT_TIMEOUT_MS",
    "DEFAULT_NAVIGATION_TIMEOUT_MS",
]
