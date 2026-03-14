"""Trust integration for skills.

This module provides trust checking for project-level skills,
integrating with the TrustStore and SkillDiscovery.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from .discovery import Skill, SkillDiscovery, SkillScope
from ..trust.detector import TrustStatus, check_project_trust
from ..trust.store import TrustStore, get_trust_store

logger = logging.getLogger("framework.skills.trust")


@dataclass
class TrustCheckResult:
    """Result of checking trust for project-level skills."""

    trusted_skills: list[Skill] = field(default_factory=list)
    untrusted_skills: list[Skill] = field(default_factory=list)
    project_path: Path | None = None
    trust_status: TrustStatus | None = None
    consent_needed: bool = False


def check_project_skills_trust(
    project_path: Path | str | None = None,
    trust_store: TrustStore | None = None,
) -> TrustCheckResult:
    """Check trust status for project-level skills.

    Args:
        project_path: Path to the project. Defaults to current directory.
        trust_store: TrustStore instance. If None, uses default.

    Returns:
        TrustCheckResult with trusted/untrusted skills split
    """
    if trust_store is None:
        trust_store = get_trust_store()

    project_path = Path(project_path) if project_path else Path.cwd()

    trust_status = check_project_trust(project_path, trust_store)

    if trust_status.is_trusted:
        discovery = SkillDiscovery(project_path=project_path)
        project_skills = discovery.scan_project()

        logger.info(
            "Project '%s' is trusted, loading %d project-level skills",
            trust_status.remote_url or "local",
            len(project_skills),
        )

        return TrustCheckResult(
            trusted_skills=project_skills,
            untrusted_skills=[],
            project_path=project_path,
            trust_status=trust_status,
            consent_needed=False,
        )

    discovery = SkillDiscovery(project_path=project_path)
    project_skills = discovery.scan_project()

    logger.info(
        "Project '%s' is untrusted, %d project-level skills require consent",
        trust_status.remote_url or "local",
        len(project_skills),
    )

    return TrustCheckResult(
        trusted_skills=[],
        untrusted_skills=project_skills,
        project_path=project_path,
        trust_status=trust_status,
        consent_needed=len(project_skills) > 0,
    )


def get_all_trusted_skills(
    project_path: Path | str | None = None,
    trust_store: TrustStore | None = None,
) -> list[Skill]:
    """Get all skills that can be loaded without consent.

    This includes:
    - Framework skills (always trusted)
    - User skills (always trusted)
    - Project skills (if project is trusted)

    Args:
        project_path: Path to the project. Defaults to current directory.
        trust_store: TrustStore instance.

    Returns:
        List of all trusted skills
    """
    if trust_store is None:
        trust_store = get_trust_store()

    project_path = Path(project_path) if project_path else Path.cwd()

    discovery = SkillDiscovery(project_path=project_path)

    trusted_skills = []

    trusted_skills.extend(discovery.scan_framework())
    logger.debug("Loaded %d framework skills", len(discovery.scan_framework()))

    trusted_skills.extend(discovery.scan_user())
    logger.debug("Loaded %d user skills", len(discovery.scan_user()))

    trust_status = check_project_trust(project_path, trust_store)
    if trust_status.is_trusted:
        trusted_skills.extend(discovery.scan_project())
        logger.debug("Loaded %d trusted project skills", len(discovery.scan_project()))

    return trusted_skills


def filter_skills_by_trust(
    skills: list[Skill],
    project_path: Path | str | None = None,
    trust_store: TrustStore | None = None,
) -> TrustCheckResult:
    """Filter a list of skills by trust status.

    Args:
        skills: Skills to filter
        project_path: Project path for trust checking
        trust_store: TrustStore instance

    Returns:
        TrustCheckResult with separated skills
    """
    if trust_store is None:
        trust_store = get_trust_store()

    project_path = Path(project_path) if project_path else Path.cwd()
    trust_status = check_project_trust(project_path, trust_store)

    if trust_status.is_trusted:
        return TrustCheckResult(
            trusted_skills=skills,
            untrusted_skills=[],
            project_path=project_path,
            trust_status=trust_status,
            consent_needed=False,
        )

    return TrustCheckResult(
        trusted_skills=[],
        untrusted_skills=skills,
        project_path=project_path,
        trust_status=trust_status,
        consent_needed=len(skills) > 0,
    )
