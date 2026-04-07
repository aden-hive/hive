"""MCP registry pipeline stage.

Resolves MCP server references from the agent config against the global
registry (``~/.hive/mcp_registry/installed.json``) and registers tools.
Replaces the per-agent ``mcp_servers.json`` pattern with declarative
name-based references.

Agent config declares servers by name::

    {"mcp_servers": [{"name": "hive-tools"}, {"name": "gcu-tools"}]}

The stage resolves each name from the global registry at ``initialize()``
time and injects the resolved ``ToolRegistry`` into the pipeline context.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from framework.pipeline.registry import register
from framework.pipeline.stage import PipelineContext, PipelineResult, PipelineStage

logger = logging.getLogger(__name__)


@register("mcp_registry")
class McpRegistryStage(PipelineStage):
    """Resolve MCP tools from the global registry.

    On ``initialize()``, connects to MCP servers declared in the agent
    config.  On ``process()``, injects ``tools`` and ``tool_executor``
    into the pipeline context metadata for downstream consumption.
    """

    order = 50

    def __init__(
        self,
        server_refs: list[dict[str, Any]] | None = None,
        agent_path: str | Path | None = None,
        **kwargs: Any,
    ) -> None:
        """
        Args:
            server_refs: List of ``{"name": "server-name"}`` dicts from
                the agent config's ``mcp_servers`` field.
            agent_path: Path to the agent directory. If a ``mcp_servers.json``
                file exists there, it's loaded as a fallback.
        """
        self._server_refs = server_refs or []
        self._agent_path = Path(agent_path) if agent_path else None
        self._tool_registry: Any = None

    async def initialize(self) -> None:
        """Connect to MCP servers and discover tools."""
        from framework.loader.mcp_registry import MCPRegistry
        from framework.loader.tool_registry import ToolRegistry

        self._tool_registry = ToolRegistry()
        registry = MCPRegistry()

        # 1. Resolve named server refs from global registry
        if self._server_refs:
            names = [ref["name"] for ref in self._server_refs if ref.get("name")]
            if names:
                configs = registry.resolve_for_agent(include=names)
                if configs:
                    self._tool_registry.load_registry_servers(configs)
                    logger.info(
                        "McpRegistryStage: resolved %d servers from registry",
                        len(configs),
                    )

        # 2. Fallback: load mcp_servers.json if it exists (backward compat)
        if self._agent_path:
            mcp_json = self._agent_path / "mcp_servers.json"
            if mcp_json.exists():
                self._tool_registry.load_mcp_config(mcp_json)
                logger.info(
                    "McpRegistryStage: loaded mcp_servers.json from %s",
                    self._agent_path.name,
                )

    async def process(self, ctx: PipelineContext) -> PipelineResult:
        """Inject resolved tools into pipeline context."""
        if self._tool_registry:
            ctx.metadata["tool_registry"] = self._tool_registry
            ctx.metadata["tools"] = list(
                self._tool_registry.get_tools().values()
            )
            ctx.metadata["tool_executor"] = self._tool_registry.get_executor()
        return PipelineResult(action="continue")
