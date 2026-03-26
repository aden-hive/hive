"""Skill configuration dataclasses.

Handles agent-level skill configuration from module-level variables
(``default_skills`` and ``skills``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DefaultSkillConfig:
    """Configuration for a single default skill."""

    enabled: bool = True
    overrides: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DefaultSkillConfig:
        enabled = data.get("enabled", True)
        overrides = {k: v for k, v in data.items() if k != "enabled"}
        return cls(enabled=enabled, overrides=overrides)


@dataclass
class SkillsConfig:
    """Agent-level skill configuration.

    Built from module-level variables in agent.py::

        # Pre-activated community skills
        skills = ["deep-research", "code-review"]

        # Default skill configuration
        default_skills = {
            "hive.note-taking": {"enabled": True},
            "hive.batch-ledger": {"enabled": True, "checkpoint_every_n": 10},
            "hive.quality-monitor": {"enabled": False},
        }
    """

    # Per-default-skill config, keyed by skill name (e.g. "hive.note-taking")
    default_skills: dict[str, DefaultSkillConfig] = field(default_factory=dict)

    # Pre-activated community skills (by name)
    skills: list[str] = field(default_factory=list)

    # Master switch: disable all default skills at once
    all_defaults_disabled: bool = False

    def is_default_enabled(self, skill_name: str) -> bool:
        """Check if a specific default skill is enabled."""
        if self.all_defaults_disabled:
            return False
        config = self.default_skills.get(skill_name)
        if config is None:
            return True  # enabled by default
        return config.enabled

    def get_default_overrides(self, skill_name: str) -> dict[str, Any]:
        """Get skill-specific configuration overrides."""
        config = self.default_skills.get(skill_name)
        if config is None:
            return {}
        return config.overrides

    @classmethod
    def from_agent_vars(
        cls,
        default_skills: dict[str, Any] | None = None,
        skills: list[str] | None = None,
    ) -> SkillsConfig:
        """Build config from agent module-level variables.

        Args:
            default_skills: Dict from agent module, e.g.
                ``{"hive.note-taking": {"enabled": True}}``
            skills: List of pre-activated skill names from agent module
        """
        all_disabled = False
        parsed_defaults: dict[str, DefaultSkillConfig] = {}

        if default_skills:
            for name, config_dict in default_skills.items():
                if name == "_all":
                    if isinstance(config_dict, dict) and not config_dict.get("enabled", True):
                        all_disabled = True
                    continue
                if isinstance(config_dict, dict):
                    parsed_defaults[name] = DefaultSkillConfig.from_dict(config_dict)
                elif isinstance(config_dict, bool):
                    parsed_defaults[name] = DefaultSkillConfig(enabled=config_dict)

        return cls(
            default_skills=parsed_defaults,
            skills=list(skills or []),
            all_defaults_disabled=all_disabled,
        )
