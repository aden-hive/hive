"""CLI consent prompt for loading untrusted project-level skills.

This module provides interactive CLI prompts for users to consent to
loading skills from untrusted repositories.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .discovery import Skill
    from ..trust.detector import TrustStatus
else:
    Skill = None
    TrustStatus = None

logger = logging.getLogger("framework.skills.consent")


class ConsentChoice(Enum):
    """User's consent choice."""

    TRUST_ONCE = "trust_once"
    TRUST_FOREVER = "trust_forever"
    DONT_LOAD = "dont_load"


@dataclass
class ConsentResult:
    """Result of a consent prompt."""

    choice: ConsentChoice
    trusted_skills: list[str]
    rejected_skills: list[str]


def prompt_for_skill_consent(
    skills: list["Skill"],
    project_url: Optional[str] = None,
    non_interactive: bool = False,
) -> ConsentResult:
    """Prompt user for consent to load untrusted project-level skills.

    Args:
        skills: List of untrusted skills
        project_url: The git remote URL of the project
        non_interactive: If True, don't prompt and return DONT_LOAD

    Returns:
        ConsentResult with user's choice
    """
    if not skills:
        return ConsentResult(
            choice=ConsentChoice.TRUST_ONCE,
            trusted_skills=[],
            rejected_skills=[],
        )

    skill_names = [s.name if hasattr(s, "name") else str(s) for s in skills]

    _display_security_notice(project_url)

    print("\nThe following skills from this repository require your consent to load:")
    print("-" * 60)

    for i, skill in enumerate(skills, 1):
        name = skill.name if hasattr(skill, "name") else str(skill)
        desc = skill.description if hasattr(skill, "description") else "No description"
        location = skill.location if hasattr(skill, "location") else "Unknown"

        print(f"\n{i}. {name}")
        print(f"   Description: {desc}")
        print(f"   Location: {location}")

    print("\n" + "-" * 60)

    if non_interactive:
        print("\n[non-interactive mode] Automatically declining untrusted skills")
        logger.info("Non-interactive mode: rejected %d untrusted skills", len(skills))
        return ConsentResult(
            choice=ConsentChoice.DONT_LOAD,
            trusted_skills=[],
            rejected_skills=skill_names,
        )

    print("\nDo you want to load these skills?")
    print("  [1] Trust once - Load now, don't persist")
    print("  [2] Trust forever - Load now and trust this repository permanently")
    print("  [3] Don't load - Skip these skills")

    while True:
        try:
            choice = input("\nEnter your choice (1/2/3): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nInput interrupted. Not loading untrusted skills.")
            return ConsentResult(
                choice=ConsentChoice.DONT_LOAD,
                trusted_skills=[],
                rejected_skills=skill_names,
            )

        if choice == "1":
            print("\n[OK] Loading skills for this session only.")
            logger.info(
                "User chose to trust once: %d skills from %s",
                len(skills),
                project_url or "local",
            )
            return ConsentResult(
                choice=ConsentChoice.TRUST_ONCE,
                trusted_skills=skill_names,
                rejected_skills=[],
            )
        elif choice == "2":
            print("\n[OK] Loading skills and marking repository as trusted.")
            logger.info(
                "User chose to trust forever: %d skills from %s",
                len(skills),
                project_url or "local",
            )
            return ConsentResult(
                choice=ConsentChoice.TRUST_FOREVER,
                trusted_skills=skill_names,
                rejected_skills=[],
            )
        elif choice == "3":
            print("\n[OK] Skipping untrusted skills.")
            logger.info(
                "User rejected untrusted skills: %d from %s",
                len(skills),
                project_url or "local",
            )
            return ConsentResult(
                choice=ConsentChoice.DONT_LOAD,
                trusted_skills=[],
                rejected_skills=skill_names,
            )
        else:
            print("Invalid choice. Please enter 1, 2, or 3.")


def _display_security_notice(project_url: Optional[str] = None) -> None:
    """Display security warning about loading skills from untrusted repos."""
    print("\n" + "=" * 60)
    print("⚠️  SECURITY NOTICE")
    print("=" * 60)
    print("""
Project-level skills are loaded from an external repository.
The SKILL.md files in this repository could contain arbitrary
instructions that will be injected into your agent's system prompt.

This is a potential PROMPT INJECTION risk if:
- You don't trust the source of this repository
- The repository owner is unknown or unverified
- The skills were modified by a third party

Only trust skills from repositories you control or that come
from trusted organizations.
""")
    if project_url:
        print(f"Repository URL: {project_url}")
    print("=" * 60)


def display_trust_status(
    project_path: Path | str | None = None,
    trust_status: "TrustStatus | None" = None,
) -> None:
    """Display the trust status of a project."""
    if trust_status is None:
        from ..trust.detector import check_project_trust

        trust_status = check_project_trust(project_path)

    print("\n" + "-" * 50)
    print("Project Trust Status")
    print("-" * 50)

    if trust_status.is_trusted:
        print(f"✓ Trusted")
    else:
        print(f"✗ Not Trusted")

    print(f"\nReason: {trust_status.reason}")

    if trust_status.remote_url:
        print(f"\nRemote URL: {trust_status.remote_url}")

    if trust_status.matched_org:
        print(f"Matched trusted org: {trust_status.matched_org}")

    print("-" * 50)
