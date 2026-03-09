"""Load MCP server config files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_mcp_server_entries(config_path: Path) -> tuple[Path, list[dict[str, Any]]]:
    """Load and normalize MCP server entries from config."""
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    base_dir = config_path.parent
    server_list = config.get("servers", [])
    if not server_list and "servers" not in config:
        server_list = [{"name": name, **cfg} for name, cfg in config.items()]
    return base_dir, server_list
