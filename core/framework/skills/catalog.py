"""Skill catalog — in-memory index with system prompt generation.

Builds the XML catalog injected into the system prompt for model-driven
skill activation per the Agent Skills standard.
"""

from __future__ import annotations

import logging
from xml.sax.saxutils import escape

from framework.skills.parser import ParsedSkill
from framework.skills.skill_errors import SkillErrorCode, log_skill_error

logger = logging.getLogger(__name__)

# Upper bound on the raw `<available_skills>` XML body, in characters.
# When the full catalog (with <description> entries) exceeds this, we fall
# back to the compact variant that drops descriptions but keeps every skill
# visible. Preserving awareness of every skill beats truncating entries.
_COMPACT_THRESHOLD_CHARS = 5000

_MANDATORY_HEADER_FULL = """## Skills (mandatory)
Before replying: scan <available_skills> <description> entries.
- If exactly one skill clearly applies: read its SKILL.md at <location> with `read_file`, then follow it.
- If multiple could apply: choose the most specific one, then read/follow it.
- If none clearly apply: do not read any SKILL.md.
Constraints: never read more than one skill up front; only read after selecting.
- When a skill drives external API writes (Gmail, Calendar, GitHub, etc.),
  assume rate limits: prefer fewer larger writes, avoid tight one-item loops,
  serialize bursts when possible, and respect 429/Retry-After.


The following skills provide specialized instructions for specific tasks.
Use `read_file` to load a skill's SKILL.md when the task matches its description.
When a skill file references a relative path, resolve it against the
skill directory (parent of SKILL.md) and use that absolute path in tool commands."""

_MANDATORY_HEADER_COMPACT = """## Skills (mandatory)
Before replying: scan <available_skills> <name> entries.
- If exactly one skill clearly applies: read its SKILL.md at <location> with `read_file`, then follow it.
- If multiple could apply: choose the most specific one, then read/follow it.
- If none clearly apply: do not read any SKILL.md.
Constraints: never read more than one skill up front; only read after selecting.
- When a skill drives external API writes (Gmail, Calendar, GitHub, etc.),
  assume rate limits: prefer fewer larger writes, avoid tight one-item loops,
  serialize bursts when possible, and respect 429/Retry-After.


The following skills provide specialized instructions for specific tasks.
Use `read_file` to load a skill's SKILL.md when the task matches its name.
When a skill file references a relative path, resolve it against the
skill directory (parent of SKILL.md) and use that absolute path in tool commands."""


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

        Returns empty string when no skills are present. Otherwise returns
        a mandatory pre-reply checklist + decision rules + rate-limit note,
        followed by the <available_skills> XML body.

        When the full XML body exceeds ``_COMPACT_THRESHOLD_CHARS``, the
        compact variant is emitted instead: <description> elements are
        dropped so every skill stays visible before any gets truncated.
        """
        all_skills = sorted(self._skills.values(), key=lambda s: s.name)
        if not all_skills:
            return ""

        full_xml = self._render_xml(all_skills, compact=False)
        if len(full_xml) <= _COMPACT_THRESHOLD_CHARS:
            return f"{_MANDATORY_HEADER_FULL}\n\n{full_xml}"

        compact_xml = self._render_xml(all_skills, compact=True)
        return f"{_MANDATORY_HEADER_COMPACT}\n\n{compact_xml}"

    @staticmethod
    def _render_xml(skills: list[ParsedSkill], *, compact: bool) -> str:
        """Render the `<available_skills>` block.

        ``compact=True`` drops `<description>` to preserve skill awareness
        when the catalog would otherwise blow the char budget.
        """
        lines = ["<available_skills>"]
        for skill in skills:
            lines.append("  <skill>")
            lines.append(f"    <name>{escape(skill.name)}</name>")
            if not compact:
                lines.append(f"    <description>{escape(skill.description)}</description>")
            lines.append(f"    <location>{escape(skill.location)}</location>")
            lines.append("  </skill>")
        lines.append("</available_skills>")
        return "\n".join(lines)

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
                log_skill_error(
                    logger,
                    "warning",
                    SkillErrorCode.SKILL_NOT_FOUND,
                    what=f"Pre-activated skill '{name}' not found in catalog",
                    why="The skill was listed for pre-activation but was not discovered.",
                    fix=f"Check that a SKILL.md for '{name}' exists in a scanned directory.",
                )
                continue
            if self.is_activated(name):
                continue  # Already activated, skip duplicate

            self.mark_activated(name)
            parts.append(f"--- Pre-Activated Skill: {skill.name} ---\n{skill.body}")

        return "\n\n".join(parts)
