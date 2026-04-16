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
}


def is_batch_scenario(text: str) -> bool:
    """Deprecated: batch auto-detection is no longer used.

    Kept as a no-op so the agent_loop call site (which wraps it in an
    ``if ctx.default_skill_batch_nudge:`` guard that's also now always
    empty) can stay unchanged until a broader cleanup.  The old
    ``_batch_ledger`` shared-buffer feature was replaced by the
    per-colony SQLite task queue (``hive.colony-progress-tracker``),
    which lives in ``progress.db`` and is authoritative for batch
    state across workers and runs.
    """
    return False


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


# Ordered list of default skills (name → directory).
#
# Removed on 2026-04-15 as part of the colony-progress-tracker rollout:
#   - hive.task-decomposition — steps table in progress.db supersedes
#     in-memory ``_working_notes → Current Plan`` decomposition.
#   - hive.batch-ledger       — tasks table in progress.db supersedes
#     the ``_batch_ledger`` dict-shaped queue with its pending →
#     in_progress → completed/failed/skipped state machine.
# Both were duplicating state that belongs in SQLite.
SKILL_REGISTRY: dict[str, str] = {
    "hive.note-taking": "note-taking",
    "hive.context-preservation": "context-preservation",
    "hive.quality-monitor": "quality-monitor",
    "hive.error-recovery": "error-recovery",
    "hive.colony-progress-tracker": "colony-progress-tracker",
    "hive.writing-hive-skills": "writing-hive-skills",
}

# Shared buffer keys referenced by the remaining default skills (used
# for permission auto-inclusion). The dead keys for batch-ledger,
# task-decomposition, the handoff buffer, and the error-log buffers
# were removed when those features migrated to progress.db.
DATA_BUFFER_KEYS: list[str] = [
    # note-taking
    "_working_notes",
    "_notes_updated_at",
    # context-preservation
    "_preserved_data",
    # quality-monitor
    "_quality_log",
    "_quality_degradation_count",
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
        """Deprecated: always returns None.

        The ``hive.batch-ledger`` default skill was removed when batch
        tracking moved into ``progress.db`` (``hive.colony-progress-
        tracker``). Callers in agent_host, colony_runtime, and
        orchestrator still read this property; returning None keeps
        them functional with no system-prompt nudge.
        """
        return None

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
