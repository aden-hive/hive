"""
MCP Server for Agent Building Tools

Exposes tools for building goal-driven agents via the Model Context Protocol.
This module serves as the entry point that initializes the FastMCP server and
registers all tool handlers from their respective modules.

Architecture:
    This file was refactored from a monolithic 3,237-line module into a modular
    structure following the single-responsibility principle. Each handler module
    registers its tools on the shared FastMCP instance via a register(mcp) function.

    core/framework/mcp/
    ├── __init__.py                    # Public exports
    ├── agent_builder_server.py        # Server init + handler registration (this file)
    ├── session.py                     # Session model & persistence
    ├── handlers/
    │   ├── __init__.py
    │   ├── session_handler.py         # Session CRUD tools
    │   ├── goal_handler.py            # Goal definition tools
    │   ├── graph_handler.py           # Node/edge CRUD tools
    │   ├── export_handler.py          # Graph export + README generation
    │   ├── mcp_server_handler.py      # External MCP server management
    │   ├── simulation_handler.py      # Node/graph simulation tools
    │   ├── evaluation_handler.py      # Evaluation rules + plan tools
    │   ├── test_generation_handler.py # Test guideline generation tools
    │   └── test_execution_handler.py  # Test run/debug/list tools
    └── validation/
        ├── __init__.py
        └── validators.py              # Graph validation + credential checks

Usage:
    python -m framework.mcp.agent_builder_server
"""

from mcp.server import FastMCP

# Initialize MCP server
mcp = FastMCP("agent-builder")

# Register all tool handlers
from framework.mcp.handlers import (  # noqa: E402
    evaluation_handler,
    export_handler,
    goal_handler,
    graph_handler,
    mcp_server_handler,
    session_handler,
    simulation_handler,
    test_execution_handler,
    test_generation_handler,
)
from framework.mcp.validation import validators  # noqa: E402

session_handler.register(mcp)
goal_handler.register(mcp)
graph_handler.register(mcp)
validators.register(mcp)
export_handler.register(mcp)
mcp_server_handler.register(mcp)
simulation_handler.register(mcp)
evaluation_handler.register(mcp)
test_generation_handler.register(mcp)
test_execution_handler.register(mcp)

# Re-export for backwards compatibility
from framework.mcp.handlers.test_generation_handler import load_plan_from_json  # noqa: E402, F401
from framework.mcp.session import (  # noqa: E402, F401
    BuildSession,
    get_session,
    save_session as _save_session,
)

# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    mcp.run()
