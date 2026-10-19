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
    register_interact_tools,
    register_lifecycle_tools,
    register_navigation_tools,
    register_script_tools,
    register_tab_tools,
)

# Constants
DEFAULT_TIMEOUT_MS = 30000
DEFAULT_NAVIGATION_TIMEOUT_MS = 60000


def register_tools(mcp: FastMCP) -> None:
    """Register all GCU browser tools with the MCP server.

    Tools are organized into categories:
    - Lifecycle: browser_setup, browser_status, browser_stop (browser_open lazy-creates the context)
    - Tabs: browser_tabs, browser_open, browser_close, browser_activate_tab
    - Navigation: browser_navigate, browser_reload
    - Inspection: browser_screenshot, browser_snapshot, browser_console, browser_html,
                  browser_shadow_query
    - Interact: browser_interact (unified click / type / key / hover / scroll / drag /
                screenshot / zoom / wait) and browser_select (dropdowns)
    - Advanced: browser_evaluate, browser_get_text,
                  browser_resize, browser_upload, browser_dialog_respond
    - Script:   browser_script (run a skill-bundled orchestration script)
    """
    register_lifecycle_tools(mcp)
    register_tab_tools(mcp)
    register_navigation_tools(mcp)
    register_inspection_tools(mcp)
    register_interact_tools(mcp)
    register_advanced_tools(mcp)
    register_script_tools(mcp)


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
