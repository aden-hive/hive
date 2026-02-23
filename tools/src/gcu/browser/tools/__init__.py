"""
Browser tools organized by category.

This package provides browser automation tools for GCU nodes:
- lifecycle: Start, stop, status, profiles
- tabs: Tab management (open, close, focus, list)
- navigation: URL navigation and history
- inspection: Page content extraction (snapshot, screenshot, console, pdf)
- interactions: Element interactions (click, type, fill, etc.)
- advanced: Wait, evaluate, resize, upload, dialog handling
- agents: Create isolated agent contexts from shared profiles
"""

from .advanced import register_advanced_tools
from .agent_profile import register_agent_tools
from .inspection import register_inspection_tools
from .interactions import register_interaction_tools
from .lifecycle import register_lifecycle_tools
from .navigation import register_navigation_tools
from .tabs import register_tab_tools

__all__ = [
    "register_lifecycle_tools",
    "register_tab_tools",
    "register_navigation_tools",
    "register_inspection_tools",
    "register_interaction_tools",
    "register_advanced_tools",
    "register_agent_tools",
]
