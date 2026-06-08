#!/usr/bin/env python3
"""chart-tools MCP server entry point.

Wired into _DEFAULT_LOCAL_SERVERS in core/framework/loader/mcp_registry.py
so that running ``uv run python chart_tools_server.py --stdio`` from this
directory starts the server. The cwd of ``tools/`` puts ``src/chart_tools``
on the import path via uv's workspace setup.
"""

from __future__ import annotations

from chart_tools.server import main

if __name__ == "__main__":
    main()
