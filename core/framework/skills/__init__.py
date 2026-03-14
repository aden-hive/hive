"""Skills module for Agent Skills standard implementation.

This module provides skill discovery, trust gating, and consent handling
for the Agent Skills specification (agentskills.io).
"""

from .consent import (
    ConsentChoice,
    ConsentResult,
    display_trust_status,
    prompt_for_skill_consent,
)
from .discovery import (
    Skill,
    SkillDiscovery,
    SkillScope,
    generate_skill_catalog,
)
from .trust import (
    TrustCheckResult,
    check_project_skills_trust,
    filter_skills_by_trust,
    get_all_trusted_skills,
)

__all__ = [
    "Skill",
    "SkillDiscovery",
    "SkillScope",
    "generate_skill_catalog",
    "TrustCheckResult",
    "check_project_skills_trust",
    "filter_skills_by_trust",
    "get_all_trusted_skills",
    "ConsentChoice",
    "ConsentResult",
    "prompt_for_skill_consent",
    "display_trust_status",
]
