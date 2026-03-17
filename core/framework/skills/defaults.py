"""DefaultSkillManager — load, configure, and inject built-in default skills.

Default skills are SKILL.md packages shipped with the framework that provide
runtime operational protocols (note-taking, batch tracking, error recovery, etc.).
"""

from __future__ import annotations

import logging
from pathlib import Path

from framework.skills.config import SkillsConfig
from framework.skills.parser import ParsedSkill, parse_skill_md

logger = logging.getLogger(__name__)

# Default skills directory relative to this module
_DEFAULT_SKILLS_DIR = Path(__file__).parent / "_default_skills"

# Ordered list of default skills (name → directory)
SKILL_REGISTRY: dict[str, str] = {
    "hive.note-taking": "note-taking",
    "hive.batch-ledger": "batch-ledger",
    "hive.context-preservation": "context-preservation",
    "hive.quality-monitor": "quality-monitor",
    "hive.error-recovery": "error-recovery",
    "hive.task-decomposition": "task-decomposition",
}

# All shared memory keys used by default skills (for permission auto-inclusion)
SHARED_MEMORY_KEYS: list[str] = [
    # note-taking
    "_working_notes",
    "_notes_updated_at",
    # batch-ledger
    "_batch_ledger",
    "_batch_total",
    "_batch_completed",
    "_batch_failed",
    # context-preservation
    "_handoff_context",
    "_preserved_data",
    # quality-monitor
    "_quality_log",
    "_quality_degradation_count",
    # error-recovery
    "_error_log",
    "_failed_tools",
    "_escalation_needed",
    # task-decomposition
    "_subtasks",
    "_iteration_budget_remaining",
]


class DefaultSkillManager:
    """Manages loading, configuration, and prompt generation for default skills."""

    def __init__(self, config: SkillsConfig | None = None):
        self._config = config or SkillsConfig()
        self._skills: dict[str, ParsedSkill] = {}
        self._loaded = False

    def load(self) -> None:
        """Load all enabled default skill SKILL.md files."""
        if self._loaded:
            return

        for skill_name, dir_name in SKILL_REGISTRY.items():
            if not self._config.is_default_enabled(skill_name):
                logger.info("Default skill '%s' disabled by config", skill_name)
                continue

            skill_path = _DEFAULT_SKILLS_DIR / dir_name / "SKILL.md"
            if not skill_path.is_file():
                logger.error("Default skill SKILL.md not found: %s", skill_path)
                continue

            parsed = parse_skill_md(skill_path, source_scope="framework")
            if parsed is None:
                logger.error("Failed to parse default skill: %s", skill_path)
                continue

            self._skills[skill_name] = parsed

        self._loaded = True

    def build_protocols_prompt(self) -> str:
        """Build the combined operational protocols section.

        Extracts protocol sections from all enabled default skills and
        combines them into a single ``## Operational Protocols`` block
        for system prompt injection.

        Returns empty string if all defaults are disabled.
        """
        if not self._skills:
            return ""

        parts: list[str] = ["## Operational Protocols\n"]

        for skill_name in SKILL_REGISTRY:
            skill = self._skills.get(skill_name)
            if skill is None:
                continue
            # Use the full body — each SKILL.md contains exactly one protocol section
            parts.append(skill.body)

        if len(parts) <= 1:
            return ""

        combined = "\n\n".join(parts)

        # Token budget warning (approximate: 1 token ≈ 4 chars)
        approx_tokens = len(combined) // 4
        if approx_tokens > 2000:
            logger.warning(
                "Default skill protocols exceed 2000 token budget "
                "(~%d tokens, %d chars). Consider trimming.",
                approx_tokens,
                len(combined),
            )

        return combined

    def log_active_skills(self) -> None:
        """Log which default skills are active and their configuration."""
        if not self._skills:
            logger.info("Default skills: all disabled")
            return

        active = []
        for skill_name in SKILL_REGISTRY:
            if skill_name in self._skills:
                overrides = self._config.get_default_overrides(skill_name)
                if overrides:
                    active.append(f"{skill_name} ({overrides})")
                else:
                    active.append(skill_name)

        logger.info("Default skills active: %s", ", ".join(active))

    @property
    def active_skill_names(self) -> list[str]:
        """Names of all currently active default skills."""
        return list(self._skills.keys())

    @property
    def active_skills(self) -> dict[str, ParsedSkill]:
        """All active default skills keyed by name."""
        return dict(self._skills)
