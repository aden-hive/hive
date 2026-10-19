"""Hive Agent Skills — discovery, parsing, trust gating, and injection of SKILL.md packages.

Implements the open Agent Skills standard (agentskills.io) for portable
skill discovery and activation, plus built-in default skills for runtime
operational discipline, and AS-13 trust gating for project-scope skills.
"""

from framework.skills.catalog import SkillCatalog
from framework.skills.config import DefaultSkillConfig, SkillsConfig
from framework.skills.defaults import DefaultSkillManager
from framework.skills.discovery import DiscoveryConfig, SkillDiscovery
from framework.skills.installer import (
    fork_skill,
    install_from_git,
    install_from_registry,
    remove_skill,
)
from framework.skills.manager import SkillsManager, SkillsManagerConfig
from framework.skills.models import TrustStatus
from framework.skills.parser import ParsedSkill, parse_skill_md
from framework.skills.registry import RegistryClient
from framework.skills.skill_errors import SkillError, SkillErrorCode, log_skill_error
from framework.skills.trust import TrustedRepoStore, TrustGate
from framework.skills.validator import ValidationResult, validate_strict

__all__ = [
    "DefaultSkillConfig",
    "DefaultSkillManager",
    "DiscoveryConfig",
    "ParsedSkill",
    "RegistryClient",
    "SkillCatalog",
    "SkillDiscovery",
    "SkillError",
    "SkillErrorCode",
    "SkillsConfig",
    "SkillsManager",
    "SkillsManagerConfig",
    "TrustGate",
    "TrustedRepoStore",
    "TrustStatus",
    "ValidationResult",
    "fork_skill",
    "install_from_git",
    "install_from_registry",
    "log_skill_error",
    "parse_skill_md",
    "remove_skill",
    "validate_strict",
]
