"""Data models for the Hive skill system (Agent Skills standard)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class SkillScope(StrEnum):
    """Where a skill was discovered."""

    PROJECT = "project"
    USER = "user"
    FRAMEWORK = "framework"


class TrustStatus(StrEnum):
    """Trust state of a skill entry."""

    TRUSTED = "trusted"
    PENDING_CONSENT = "pending_consent"
    DENIED = "denied"


@dataclass
class SkillEntry:
    """In-memory record for a discovered skill (PRD §4.2)."""

    name: str
    """Skill name from SKILL.md frontmatter."""

    description: str
    """Skill description from SKILL.md frontmatter."""

    location: Path
    """Absolute path to SKILL.md."""

    base_dir: Path
    """Parent directory of SKILL.md (skill root)."""

    source_scope: SkillScope
    """Which scope this skill was found in."""

    trust_status: TrustStatus = TrustStatus.TRUSTED
    """Trust state; project-scope skills start as PENDING_CONSENT before gating."""

    # Optional frontmatter fields
    license: str | None = None
    compatibility: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
