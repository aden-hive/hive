"""DefaultSkillManager — load, configure, and inject built-in default skills.

Default skills are SKILL.md packages shipped with the framework that provide
runtime operational protocols (note-taking, batch tracking, error recovery, etc.).
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

# Default config values per skill — used for {{placeholder}} substitution
_SKILL_DEFAULTS: dict[str, dict[str, Any]] = {
    "hive.quality-monitor": {"assessment_interval": 5},
    "hive.error-recovery": {"max_retries_per_tool": 3},
    "hive.context-preservation": {"warn_at_usage_ratio_pct": 45},
    "hive.batch-ledger": {"checkpoint_every_n": 5},
}

# Keywords that indicate a batch processing scenario (DS-12)
_BATCH_KEYWORDS: tuple[str, ...] = (
    "list of",
    "collection of",
    "set of",
    "batch of",
    "each item",
    "for each",
    "process all",
    "records",
    "entries",
    "rows",
    "items",
)

_BATCH_INIT_NUDGE = (
    "Note: your input appears to describe a batch operation. "
    "Initialize `_batch_ledger` with the total item count before processing."
)


def is_batch_scenario(text: str) -> bool:
    """Return True if *text* contains batch-processing indicators (DS-12)."""
    lower = text.lower()
    return any(kw in lower for kw in _BATCH_KEYWORDS)


def _apply_overrides(skill_name: str, body: str, overrides: dict[str, Any]) -> str:
    """Substitute {{placeholder}} values in a skill body using overrides + defaults."""
    defaults = _SKILL_DEFAULTS.get(skill_name, {})
    # Convert float warn_at_usage_ratio → warn_at_usage_ratio_pct for the placeholder
    if "warn_at_usage_ratio" in overrides:
        overrides = dict(overrides)
        overrides.setdefault("warn_at_usage_ratio_pct", int(float(overrides["warn_at_usage_ratio"]) * 100))
    values = {**defaults, **overrides}
    for key, val in values.items():
        body = body.replace(f"{{{{{key}}}}}", str(val))
    return body


# Ordered list of default skills (name → directory)
SKILL_REGISTRY: dict[str, str] = {
    "hive.note-taking": "note-taking",
    "hive.batch-ledger": "batch-ledger",
    "hive.context-preservation": "context-preservation",
    "hive.quality-monitor": "quality-monitor",
    "hive.error-recovery": "error-recovery",
    "hive.task-decomposition": "task-decomposition",
    "hive.writing-hive-skills": "writing-hive-skills",
}

# All shared buffer keys used by default skills (for permission auto-inclusion)
DATA_BUFFER_KEYS: list[str] = [
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

    @property
    def batch_init_nudge(self) -> str | None:
        """Nudge text to prepend to system prompt when batch input detected (DS-12).

        Returns None if ``hive.batch-ledger`` is disabled or auto_detect_batch is False.
        """
        if "hive.batch-ledger" not in self._skills:
            return None
        overrides = self._config.get_default_overrides("hive.batch-ledger")
        if overrides.get("auto_detect_batch") is False:
            return None
        return _BATCH_INIT_NUDGE

    @property
    def context_warn_ratio(self) -> float | None:
        """Token usage ratio at which to inject a context preservation warning (DS-13).

        Returns None if ``hive.context-preservation`` is disabled.
        Defaults to 0.45 when the skill is active but no override is set.
        """
        if "hive.context-preservation" not in self._skills:
            return None
        overrides = self._config.get_default_overrides("hive.context-preservation")
        return float(overrides.get("warn_at_usage_ratio", 0.45))
