"""DefaultSkillManager — load, configure, and inject built-in default skills.

Default skills are SKILL.md packages shipped with the framework. The
worker-facing operational protocols (note-taking, context-preservation,
error-recovery, quality-monitor) that used to live here were folded into
the worker system prompt — they hardly added behavior on top of the
tracker.db + report_to_parent loop. What remains are the substantive
skills: ``writing-hive-skills`` (skill authoring reference) and
``browser-automation`` (tool-gated decision tree for browser-capable
agents).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from framework.skills.config import SkillsConfig
from framework.skills.parser import ParsedSkill, parse_skill_md
from framework.skills.skill_errors import SkillErrorCode, log_skill_error

logger = logging.getLogger(__name__)

# Default skills directory relative to this module
_DEFAULT_SKILLS_DIR = Path(__file__).parent / "_default_skills"

# Default config values per skill — used for {{placeholder}} substitution.
# Currently empty (all remaining default skills are static text). Kept
# as the override mechanism if a future skill needs runtime-substituted
# values.
_SKILL_DEFAULTS: dict[str, dict[str, Any]] = {}


def _apply_overrides(skill_name: str, body: str, overrides: dict[str, Any]) -> str:
    """Substitute {{placeholder}} values in a skill body using overrides + defaults."""
    defaults = _SKILL_DEFAULTS.get(skill_name, {})
    values = {**defaults, **overrides}
    for key, val in values.items():
        body = body.replace(f"{{{{{key}}}}}", str(val))
    return body


# Ordered list of default skills (name → directory). Worker-facing
# operational protocols were retired into WORKER_SYSTEM_PROMPT; the
# remaining defaults are reference skills (writing-hive-skills) and
# tool-gated decision trees (browser-automation).
SKILL_REGISTRY: dict[str, str] = {
    "hive.writing-hive-skills": "writing-hive-skills",
    # browser-automation lives alongside the protocol skills because
    # every queen runs in a browser-capable colony today; classifying
    # it as a default makes the startup log explicit ("loaded") rather
    # than relying on tool-gating to silently pre-activate it.
    "hive.browser-automation": "browser-automation",
    # pdf is a reference skill — body stays out of the prompt until an
    # agent activates it via progressive disclosure on the description.
    "hive.pdf": "pdf",
}

# Shared buffer keys default skills used to read/write. None remaining —
# the protocol skills that needed scratch buffers (_working_notes,
# _preserved_data, _quality_log) were removed in favor of tracker.db
# upserts. Kept as an empty list so the auto-permission loop in
# ``orchestrator/context.py`` still has something to import.
DATA_BUFFER_KEYS: list[str] = []


class DefaultSkillManager:
    """Manages loading, configuration, and prompt generation for default skills."""

    def __init__(self, config: SkillsConfig | None = None):
        self._config = config or SkillsConfig()
        self._skills: dict[str, ParsedSkill] = {}
        self._loaded = False
        self._error_count = 0

    def load(self) -> None:
        """Load all enabled default skill SKILL.md files."""
        if self._loaded:
            return

        error_count = 0
        for skill_name, dir_name in SKILL_REGISTRY.items():
            if not self._config.is_default_enabled(skill_name):
                logger.info("Default skill '%s' disabled by config", skill_name)
                continue

            skill_path = _DEFAULT_SKILLS_DIR / dir_name / "SKILL.md"
            if not skill_path.is_file():
                log_skill_error(
                    logger,
                    "error",
                    SkillErrorCode.SKILL_NOT_FOUND,
                    what=f"Default skill SKILL.md not found: '{skill_path}'",
                    why=f"The framework skill '{skill_name}' is missing its SKILL.md file.",
                    fix="Reinstall the hive framework — this file is part of the package.",
                )
                error_count += 1
                continue

            parsed = parse_skill_md(skill_path, source_scope="framework")
            if parsed is None:
                log_skill_error(
                    logger,
                    "error",
                    SkillErrorCode.SKILL_PARSE_ERROR,
                    what=f"Failed to parse default skill '{skill_name}'",
                    why=f"parse_skill_md returned None for '{skill_path}'.",
                    fix="Reinstall the hive framework — this file may be corrupted.",
                )
                error_count += 1
                continue

            self._skills[skill_name] = parsed

        self._loaded = True
        self._error_count = error_count

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
            # Apply config overrides to {{placeholder}} values before injection
            overrides = self._config.get_default_overrides(skill_name)
            body = _apply_overrides(skill_name, skill.body, overrides)
            parts.append(body)

        if len(parts) <= 1:
            return ""

        combined = "\n\n".join(parts)

        # Token budget warning (approximate: 1 token ≈ 4 chars)
        approx_tokens = len(combined) // 4
        if approx_tokens > 2000:
            logger.warning(
                "Default skill protocols exceed 2000 token budget (~%d tokens, %d chars). Consider trimming.",
                approx_tokens,
                len(combined),
            )

        return combined

    def log_active_skills(self) -> None:
        """Log which default skills are active and their configuration."""
        if not self._skills:
            logger.info("Default skills: all disabled")

        # DX-3: Per-skill structured startup log
        for skill_name in SKILL_REGISTRY:
            if skill_name in self._skills:
                overrides = self._config.get_default_overrides(skill_name)
                status = f"loaded overrides={overrides}" if overrides else "loaded"
            elif not self._config.is_default_enabled(skill_name):
                status = "disabled"
            else:
                status = "error"
            logger.info(
                "skill_startup name=%s scope=framework status=%s",
                skill_name,
                status,
            )

        # Original active skills log line (preserved for backward compatibility)
        active = []
        for skill_name in SKILL_REGISTRY:
            if skill_name in self._skills:
                overrides = self._config.get_default_overrides(skill_name)
                if overrides:
                    active.append(f"{skill_name} ({overrides})")
                else:
                    active.append(skill_name)

        if active:
            logger.info("Default skills active: %s", ", ".join(active))

        # DX-3: Summary line with error count
        total = len(SKILL_REGISTRY)
        active_count = len(self._skills)
        error_count = getattr(self, "_error_count", 0)
        disabled_count = total - active_count - error_count
        logger.info(
            "Skills: %d default (%d active, %d disabled, %d error)",
            total,
            active_count,
            disabled_count,
            error_count,
        )

    @property
    def active_skill_names(self) -> list[str]:
        """Names of all currently active default skills."""
        return list(self._skills.keys())

    @property
    def active_skills(self) -> dict[str, ParsedSkill]:
        """All active default skills keyed by name."""
        return dict(self._skills)
