#!/usr/bin/env python3
"""memory-tools MCP server entry point.

Wired into _DEFAULT_LOCAL_SERVERS in core/framework/loader/mcp_registry.py
so that running ``uv run python memory_tools_server.py --stdio`` from this
directory starts the server.
"""

from __future__ import annotations

from memory_tools.server import main

if __name__ == "__main__":
    main()
