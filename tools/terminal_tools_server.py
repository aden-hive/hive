#!/usr/bin/env python3
"""terminal-tools MCP server entry point.

Wired into _DEFAULT_LOCAL_SERVERS in core/framework/loader/mcp_registry.py
so that running ``uv run python terminal_tools_server.py --stdio`` from this
directory starts the server. The cwd of ``tools/`` puts ``src/terminal_tools``
on the import path via uv's workspace setup.

Usage:
    uv run python terminal_tools_server.py --stdio       # for agent integration
    uv run python terminal_tools_server.py --port 4004   # HTTP for inspection
"""

from __future__ import annotations

from terminal_tools.server import main

if __name__ == "__main__":
    main()
