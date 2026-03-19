"""Skill catalog — in-memory index with system prompt generation.

Builds the XML catalog injected into the system prompt for model-driven
skill activation per the Agent Skills standard.
"""

from __future__ import annotations

import logging
from xml.sax.saxutils import escape

from framework.skills.parser import ParsedSkill

logger = logging.getLogger(__name__)

_BEHAVIORAL_INSTRUCTION = (
    "The following skills provide specialized instructions for specific tasks.\n"
    "When a task matches a skill's description, read the SKILL.md at the listed\n"
    "location to load the full instructions before proceeding.\n"
    "When a skill references relative paths, resolve them against the skill's\n"
    "directory (the parent of SKILL.md) and use absolute paths in tool calls."
)


class SkillCatalog:
    """In-memory catalog of discovered skills."""

    def __init__(self, skills: list[ParsedSkill] | None = None):
        self._skills: dict[str, ParsedSkill] = {}
        self._activated: set[str] = set()
        if skills:
            for skill in skills:
                self.add(skill)

    def add(self, skill: ParsedSkill) -> None:
        """Add a skill to the catalog."""
        self._skills[skill.name] = skill

    def get(self, name: str) -> ParsedSkill | None:
        """Look up a skill by name."""
        return self._skills.get(name)

    def mark_activated(self, name: str) -> None:
        """Mark a skill as activated in the current session."""
        self._activated.add(name)

    def is_activated(self, name: str) -> bool:
        """Check if a skill has been activated."""
        return name in self._activated

    @property
    def skill_count(self) -> int:
        return len(self._skills)

    @property
    def allowlisted_dirs(self) -> list[str]:
        """All skill base directories for file access allowlisting."""
        return [skill.base_dir for skill in self._skills.values()]

    def to_prompt(self) -> str:
        """Generate the catalog prompt for system prompt injection.

        Returns empty string if no community/user skills are discovered
        (default skills are handled separately by DefaultSkillManager).
        """
        # Filter out framework-scope skills (default skills) — they're
        # injected via the protocols prompt, not the catalog
        community_skills = [s for s in self._skills.values() if s.source_scope != "framework"]

        if not community_skills:
            return ""

        lines = ["<available_skills>"]
        for skill in sorted(community_skills, key=lambda s: s.name):
            lines.append("  <skill>")
            lines.append(f"    <name>{escape(skill.name)}</name>")
            lines.append(f"    <description>{escape(skill.description)}</description>")
            lines.append(f"    <location>{escape(skill.location)}</location>")
            lines.append(f"    <base_dir>{escape(skill.base_dir)}</base_dir>")
            lines.append("  </skill>")
        lines.append("</available_skills>")

        xml_block = "\n".join(lines)
        return f"{_BEHAVIORAL_INSTRUCTION}\n\n{xml_block}"

    def build_pre_activated_prompt(self, skill_names: list[str]) -> str:
        """Build prompt content for pre-activated skills.

        Pre-activated skills get their full SKILL.md body loaded into
        the system prompt at startup (tier 2), bypassing model-driven
        activation.

        Returns empty string if no skills match.
        """
        parts: list[str] = []

        for name in skill_names:
            skill = self.get(name)
            if skill is None:
                logger.warning("Pre-activated skill '%s' not found in catalog", name)
                continue
            if self.is_activated(name):
                continue  # Already activated, skip duplicate

            self.mark_activated(name)
            parts.append(f"--- Pre-Activated Skill: {skill.name} ---\n{skill.body}")

        return "\n\n".join(parts)
