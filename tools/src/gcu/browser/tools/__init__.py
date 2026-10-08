"""
Browser tools organized by category.

This package provides browser automation tools for GCU nodes:
- lifecycle: Start, stop, status
- tabs: Tab management (open, close, focus, list)
- navigation: URL navigation and history
- inspection: Page content extraction (snapshot, screenshot, console, pdf)
- interact: browser_interact (unified click / type / key / hover / scroll /
  drag / screenshot / zoom / wait) plus browser_select
- advanced: Evaluate, get_text/attribute, resize, upload, dialog handling
- script: browser_script (run a bundled Python orchestration script from a skill)
"""

from .advanced import register_advanced_tools
from .inspection import register_inspection_tools
from .interact import register_interact_tools
from .lifecycle import register_lifecycle_tools
from .navigation import register_navigation_tools
from .script import register_script_tools
from .tabs import register_tab_tools

__all__ = [
    "register_lifecycle_tools",
    "register_tab_tools",
    "register_navigation_tools",
    "register_inspection_tools",
    "register_interact_tools",
    "register_advanced_tools",
    "register_script_tools",
]
