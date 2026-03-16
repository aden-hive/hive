"""Hive skill system — implements the open Agent Skills standard.

Public API:
    SkillEntry, SkillScope, TrustStatus  — data models
    SkillDiscovery                        — scan skill directories
    TrustedRepoStore                      — persist trusted repos
    TrustGate                             — filter skills by trust
    SkillCatalog                          — in-memory index + prompt injection
"""

from framework.skills.catalog import SkillCatalog
from framework.skills.discovery import SkillDiscovery
from framework.skills.models import SkillEntry, SkillScope, TrustStatus
from framework.skills.trust import TrustGate, TrustedRepoStore

__all__ = [
    "SkillCatalog",
    "SkillDiscovery",
    "SkillEntry",
    "SkillScope",
    "TrustGate",
    "TrustedRepoStore",
    "TrustStatus",
]
