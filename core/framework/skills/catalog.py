"""Skill catalog — in-memory index of trusted skills.

Provides tier-1 catalog prompt injection (PRD §4.3) and tier-2 activation
(loading full SKILL.md body on demand).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from framework.skills.models import SkillEntry


@dataclass
class SkillCatalog:
    """In-memory index of trusted, discovered skills."""

    entries: list[SkillEntry] = field(default_factory=list)

    def to_catalog_prompt(self) -> str:
        """Render the tier-1 catalog block for system prompt injection (PRD §4.3).

        Returns an empty string when there are no skills.
        """
        if not self.entries:
            return ""

        lines = ["<available_skills>"]
        for skill in self.entries:
            lines += [
                "  <skill>",
                f"    <name>{skill.name}</name>",
                f"    <description>{skill.description}</description>",
                f"    <location>{skill.location}</location>",
                "  </skill>",
            ]
        lines.append("</available_skills>")
        lines.append("")
        lines.append(
            "The following skills provide specialized instructions for specific tasks.\n"
            "When a task matches a skill's description, read the SKILL.md at the listed\n"
            "location to load the full instructions before proceeding.\n"
            "When a skill references relative paths, resolve them against the skill's\n"
            "directory (the parent of SKILL.md) and use absolute paths in tool calls."
        )
        return "\n".join(lines)

    def get(self, name: str) -> SkillEntry | None:
        """Look up a skill by name."""
        for entry in self.entries:
            if entry.name == name:
                return entry
        return None

    def activate(self, name: str) -> str | None:
        """Load and return the full SKILL.md body (tier 2 — instructions only).

        Returns None if the skill is not found or the file cannot be read.
        """
        entry = self.get(name)
        if entry is None:
            return None
        try:
            text = entry.location.read_text(encoding="utf-8")
            return _strip_frontmatter(text)
        except OSError:
            return None


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter, returning the markdown body."""
    if not text.startswith("---"):
        return text
    rest = text[3:]
    if rest.startswith(("\n", "\r\n")):
        rest = rest[rest.index("\n") + 1 :]
    end = re.search(r"^---\s*$", rest, re.MULTILINE)
    if end is None:
        return text
    body = rest[end.end() :]
    return body.lstrip("\n")
