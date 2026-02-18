"""Reusable Agent Guardian — monitors and recovers from agent failures.

Usage::

    from framework.agents.guardian import attach_guardian

    runner._setup()
    attach_guardian(runner._agent_runtime, runner._tool_registry)
    await runner._agent_runtime.start()
"""

from .attach import attach_guardian
from .node import ALL_GUARDIAN_TOOLS, guardian_node

__all__ = [
    "attach_guardian",
    "guardian_node",
    "ALL_GUARDIAN_TOOLS",
]
