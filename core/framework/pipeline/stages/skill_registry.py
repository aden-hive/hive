"""Skill registry pipeline stage.

Discovers and loads skills. This is the ONLY place skills get loaded.
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
    """Discover skills and provide prompts."""

    order = 60

    def __init__(
        self,
        project_root: str | Path | None = None,
        interactive: bool = True,
        skills_config: Any = None,
        **kwargs: Any,
    ) -> None:
        self._project_root = Path(project_root) if project_root else None
        self._interactive = interactive
        self._skills_config = skills_config
        self.skills_manager: Any = None

    async def initialize(self) -> None:
        from framework.skills.config import SkillsConfig
        from framework.skills.manager import SkillsManager, SkillsManagerConfig

        config = SkillsManagerConfig(
            skills_config=self._skills_config or SkillsConfig(),
            project_root=self._project_root,
            interactive=self._interactive,
        )
        self.skills_manager = SkillsManager(config)
        self.skills_manager.load()
        await self.skills_manager.start_watching()
        logger.info(
            "[pipeline] SkillRegistryStage: catalog=%d chars, protocols=%d chars",
            len(self.skills_manager.skills_catalog_prompt),
            len(self.skills_manager.protocols_prompt),
        )

    async def process(self, ctx: PipelineContext) -> PipelineResult:
        return PipelineResult(action="continue")
