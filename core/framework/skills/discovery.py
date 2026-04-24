"""Skill discovery — scan standard directories for SKILL.md files.

Implements the Agent Skills standard discovery paths plus Hive-specific
locations. Resolves name collisions deterministically.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from framework.skills.parser import ParsedSkill, parse_skill_md
from framework.skills.skill_errors import SkillErrorCode, log_skill_error

logger = logging.getLogger(__name__)

# Directories to skip during scanning
_SKIP_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)

# Scope priority (higher = takes precedence)
# ``preset`` sits between framework and user: bundled alongside the
# framework distribution, but off by default — capability packs the user
# opts into per queen/colony rather than globally-enabled infra.
_SCOPE_PRIORITY = {
    "framework": 0,
    "preset": 1,
    "user": 2,
    "queen_ui": 3,
    "colony_ui": 4,
    "project": 5,
}

# Within the same scope, Hive-specific paths override cross-client paths.
# We encode this by scanning cross-client first, then Hive-specific (later wins).


@dataclass
class ExtraScope:
    """Additional scope dir to scan beyond the standard five.

    Used by :class:`framework.skills.manager.SkillsManager` to surface
    per-queen (``queen_ui``) and per-colony (``colony_ui``) skill
    directories created through the UI. The ``label`` feeds
    :attr:`ParsedSkill.source_scope` so downstream consumers (trust
    gate, UI provenance resolver) can distinguish scope origins.
    """

    directory: Path
    label: str
    # Kept for forward-compat with the priority table; discovery itself
    # relies on scan order for last-wins resolution.
    priority: int = 0


@dataclass
class DiscoveryConfig:
    """Configuration for skill discovery."""

    project_root: Path | None = None
    skip_user_scope: bool = False
    skip_framework_scope: bool = False
    max_depth: int = 4
    max_dirs: int = 2000
    # Additional scope dirs scanned between user and project scopes,
    # in the order they are provided. Use ``ExtraScope`` to tag each
    # with its logical label (``queen_ui`` / ``colony_ui``).
    extra_scopes: list[ExtraScope] = field(default_factory=list)


class SkillDiscovery:
    """Scans standard directories for SKILL.md files and resolves collisions."""

    def __init__(self, config: DiscoveryConfig | None = None):
        self._config = config or DiscoveryConfig()
        self._scanned_dirs: list[Path] = []

    @property
    def scanned_directories(self) -> list[str]:
        """Return the skill directories that were scanned during discovery.

        Populated after :meth:`discover` runs.  Used by the hot-reload
        watcher to know which directories to monitor for changes.
        """
        return [str(d) for d in self._scanned_dirs if d.exists()]

    def discover(self) -> list[ParsedSkill]:
        """Scan all scopes and return deduplicated skill list.

        Scanning order (lowest to highest precedence):
        1. Framework defaults
        2. User cross-client (~/.agents/skills/)
        3. User Hive-specific (~/.hive/skills/)
        4. Project cross-client (<project>/.agents/skills/)
        5. Project Hive-specific (<project>/.hive/skills/)

        Later entries override earlier ones on name collision.
        """
        all_skills: list[ParsedSkill] = []
        self._scanned_dirs = []

        # Framework scope (lowest precedence) — always-on infra skills.
        if not self._config.skip_framework_scope:
            framework_dir = Path(__file__).parent / "_default_skills"
            if framework_dir.is_dir():
                self._scanned_dirs.append(framework_dir)
                all_skills.extend(self._scan_scope(framework_dir, "framework"))

            # Preset scope — bundled capability packs that ship with the
            # framework but default to OFF. User opts in per queen/colony
            # via the Skills Library. ``skip_framework_scope`` covers both
            # bundled directories since they live side-by-side on disk.
            preset_dir = Path(__file__).parent / "_preset_skills"
            if preset_dir.is_dir():
                self._scanned_dirs.append(preset_dir)
                all_skills.extend(self._scan_scope(preset_dir, "preset"))

        # User scope
        if not self._config.skip_user_scope:
            home = Path.home()

            # Cross-client (lower precedence within user scope)
            user_agents = home / ".agents" / "skills"
            if user_agents.is_dir():
                self._scanned_dirs.append(user_agents)
                all_skills.extend(self._scan_scope(user_agents, "user"))

            # Hive-specific (higher precedence within user scope)
            user_hive = home / ".hive" / "skills"
            if user_hive.is_dir():
                self._scanned_dirs.append(user_hive)
                all_skills.extend(self._scan_scope(user_hive, "user"))

        # Extra scopes (queen_ui / colony_ui), scanned between user and project
        # so colony overrides beat queen overrides, and both beat user-scope.
        for extra in self._config.extra_scopes:
            if extra.directory.is_dir():
                self._scanned_dirs.append(extra.directory)
                all_skills.extend(self._scan_scope(extra.directory, extra.label))

        # Project scope (highest precedence)
        if self._config.project_root:
            root = self._config.project_root

            # Cross-client
            project_agents = root / ".agents" / "skills"
            if project_agents.is_dir():
                self._scanned_dirs.append(project_agents)
                all_skills.extend(self._scan_scope(project_agents, "project"))

            # Hive-specific
            project_hive = root / ".hive" / "skills"
            if project_hive.is_dir():
                self._scanned_dirs.append(project_hive)
                all_skills.extend(self._scan_scope(project_hive, "project"))

        resolved = self._resolve_collisions(all_skills)

        logger.info(
            "Skill discovery: found %d skills (%d after dedup) across all scopes",
            len(all_skills),
            len(resolved),
        )
        return resolved

    def _scan_scope(self, root: Path, scope: str) -> list[ParsedSkill]:
        """Scan a single directory for skill directories containing SKILL.md."""
        skills: list[ParsedSkill] = []
        dirs_scanned = 0

        for skill_md in self._find_skill_files(root, depth=0):
            if dirs_scanned >= self._config.max_dirs:
                logger.warning(
                    "Hit max directory limit (%d) scanning %s",
                    self._config.max_dirs,
                    root,
                )
                break

            parsed = parse_skill_md(skill_md, source_scope=scope)
            if parsed is not None:
                skills.append(parsed)
            dirs_scanned += 1

        return skills

    def _find_skill_files(self, directory: Path, depth: int) -> list[Path]:
        """Recursively find SKILL.md files up to max_depth."""
        if depth > self._config.max_depth:
            return []

        results: list[Path] = []

        try:
            entries = sorted(directory.iterdir())
        except OSError:
            return []

        for entry in entries:
            if not entry.is_dir():
                continue
            if entry.name in _SKIP_DIRS:
                continue

            skill_md = entry / "SKILL.md"
            if skill_md.is_file():
                results.append(skill_md)
            else:
                # Recurse into subdirectories
                results.extend(self._find_skill_files(entry, depth + 1))

        return results

    def _resolve_collisions(self, skills: list[ParsedSkill]) -> list[ParsedSkill]:
        """Resolve name collisions deterministically.

        Later entries in the list override earlier ones (because we scan
        from lowest to highest precedence). On collision, log a warning.
        """
        seen: dict[str, ParsedSkill] = {}

        for skill in skills:
            if skill.name in seen:
                existing = seen[skill.name]
                log_skill_error(
                    logger,
                    "warning",
                    SkillErrorCode.SKILL_COLLISION,
                    what=f"Skill name collision: '{skill.name}'",
                    why=f"'{skill.location}' overrides '{existing.location}'.",
                    fix="Rename one of the conflicting skill directories to use a unique name.",
                )
            seen[skill.name] = skill

        return list(seen.values())
