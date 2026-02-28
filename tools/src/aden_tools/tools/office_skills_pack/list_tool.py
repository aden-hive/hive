from __future__ import annotations

import os
from typing import List

from fastmcp import FastMCP

from aden_tools.tools.file_system_toolkits.security import get_secure_path


def register_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    def office_list_outputs(prefix: str, workspace_id: str, agent_id: str, session_id: str) -> dict:
        base = get_secure_path(prefix, workspace_id, agent_id, session_id)
        if not os.path.exists(base):
            return {"outputs": []}
        outs: List[str] = []
        session_root = get_secure_path("", workspace_id, agent_id, session_id)
        for root, _, files in os.walk(base):
            for f in files:
                abs_path = os.path.join(root, f)
                rel = os.path.relpath(abs_path, session_root)
                outs.append(rel.replace("\\", "/"))
        outs.sort()
        return {"outputs": outs}
