#!/usr/bin/env python3
"""chart-tools MCP server entry point.

Hive itself runs these tools in-process (core/framework/tools/harness_tools.py);
this entry point serves them over MCP for standalone use: running
``uv run python chart_tools_server.py --stdio`` from this directory starts the
server. The cwd of ``tools/`` puts ``src/chart_tools``
on the import path via uv's workspace setup.
"""

from __future__ import annotations

from chart_tools.server import main

if __name__ == "__main__":
    main()
