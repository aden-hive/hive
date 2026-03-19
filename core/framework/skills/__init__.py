"""Hive Agent Skills — discovery, parsing, trust gating, and injection of SKILL.md packages.

Implements the open Agent Skills standard (agentskills.io) for portable
skill discovery and activation, plus built-in default skills for runtime
operational discipline, and AS-13 trust gating for project-scope skills.
"""

from framework.skills.catalog import SkillCatalog
from framework.skills.config import DefaultSkillConfig, SkillsConfig
from framework.skills.defaults import DefaultSkillManager
from framework.skills.discovery import DiscoveryConfig, SkillDiscovery
from framework.skills.manager import SkillsManager, SkillsManagerConfig
from framework.skills.models import TrustStatus
from framework.skills.parser import ParsedSkill, parse_skill_md
from framework.skills.trust import TrustedRepoStore, TrustGate

__all__ = [
    "DefaultSkillConfig",
    "DefaultSkillManager",
    "DiscoveryConfig",
    "ParsedSkill",
    "SkillCatalog",
    "SkillDiscovery",
    "SkillsConfig",
    "SkillsManager",
    "SkillsManagerConfig",
    "TrustGate",
    "TrustedRepoStore",
    "TrustStatus",
    "parse_skill_md",
]
