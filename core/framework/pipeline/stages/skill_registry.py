"""Skill registry pipeline stage.

Discovers and loads skills, injects skill prompts into the pipeline
context.  Replaces the standalone ``SkillsManager`` initialization
in ``AgentHost.__init__()``.

Supports hot-reload: when ``SKILL.md`` files change on disk, the
cached prompts are rebuilt and the next pipeline execution picks
up the new values.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from framework.pipeline.registry import register
from framework.pipeline.stage import PipelineContext, PipelineResult, PipelineStage

logger = logging.getLogger(__name__)


@register("skill_registry")
class SkillRegistryStage(PipelineStage):
    """Discover skills and inject prompts into pipeline context."""

    order = 60

    def __init__(
        self,
        project_root: str | Path | None = None,
        interactive: bool = True,
        **kwargs: Any,
    ) -> None:
        self._project_root = Path(project_root) if project_root else None
        self._interactive = interactive
        self._skills_manager: Any = None

    async def initialize(self) -> None:
        """Discover skills and start hot-reload watcher."""
        from framework.skills.manager import SkillsManager, SkillsManagerConfig

        config = SkillsManagerConfig(
            project_root=self._project_root,
            interactive=self._interactive,
        )
        self._skills_manager = SkillsManager(config)
        self._skills_manager.load()
        await self._skills_manager.start_watching()

    async def process(self, ctx: PipelineContext) -> PipelineResult:
        """Inject skill prompts into pipeline context."""
        if self._skills_manager:
            ctx.metadata["skills_catalog_prompt"] = (
                self._skills_manager.skills_catalog_prompt
            )
            ctx.metadata["protocols_prompt"] = (
                self._skills_manager.protocols_prompt
            )
            ctx.metadata["skill_dirs"] = (
                self._skills_manager.allowlisted_dirs
            )
        return PipelineResult(action="continue")
