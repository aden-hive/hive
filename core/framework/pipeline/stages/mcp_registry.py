"""MCP registry pipeline stage.

Resolves MCP server references from the agent config against the global
registry and registers tools. This is the ONLY place MCP tools get loaded.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from framework.pipeline.registry import register
from framework.pipeline.stage import PipelineContext, PipelineResult, PipelineStage

logger = logging.getLogger(__name__)


@register("mcp_registry")
class McpRegistryStage(PipelineStage):
    """Resolve MCP tools from the global registry."""

    order = 50

    def __init__(
        self,
        server_refs: list[dict[str, Any]] | None = None,
        agent_path: str | Path | None = None,
        tool_registry: Any = None,
        **kwargs: Any,
    ) -> None:
        self._server_refs = server_refs or []
        self._agent_path = Path(agent_path) if agent_path else None
        self._tool_registry = tool_registry

    async def initialize(self) -> None:
        """Connect to MCP servers and discover tools."""
        if self._tool_registry is None:
            from framework.loader.tool_registry import ToolRegistry

            self._tool_registry = ToolRegistry()

        from framework.loader.mcp_registry import MCPRegistry

        registry = MCPRegistry()
        mcp_loaded = False

        # 1. From agent.json mcp_servers refs
        if self._server_refs:
            names = [ref["name"] for ref in self._server_refs if ref.get("name")]
            if names:
                configs = registry.resolve_for_agent(include=names)
                if configs:
                    self._tool_registry.load_registry_servers(
                        [asdict(c) for c in configs]
                    )
                    mcp_loaded = True
                    logger.info(
                        "[pipeline] McpRegistryStage: loaded %d servers: %s",
                        len(configs),
                        names,
                    )

        # 2. Legacy: mcp_servers.json
        if not mcp_loaded and self._agent_path:
            mcp_json = self._agent_path / "mcp_servers.json"
            if mcp_json.exists():
                self._tool_registry.load_mcp_config(mcp_json)
                mcp_loaded = True

        # 3. Fallback: all servers from global registry
        if not mcp_loaded:
            configs = registry.resolve_for_agent(profile="all")
            if configs:
                self._tool_registry.load_registry_servers(
                    [asdict(c) for c in configs]
                )
                logger.info(
                    "[pipeline] McpRegistryStage: loaded %d servers (fallback)",
                    len(configs),
                )

        total = len(self._tool_registry.get_tools())
        logger.info("[pipeline] McpRegistryStage: %d tools available", total)

    async def process(self, ctx: PipelineContext) -> PipelineResult:
        return PipelineResult(action="continue")

    @property
    def tool_registry(self):
        return self._tool_registry
