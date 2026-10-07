#!/usr/bin/env python3
"""memory-tools MCP server entry point.

Hive itself runs these tools in-process (core/framework/tools/harness_tools.py);
this entry point serves them over MCP for standalone use: running
``uv run python memory_tools_server.py --stdio`` from this directory starts
the server.
"""

from __future__ import annotations

from memory_tools.server import main

if __name__ == "__main__":
    main()
