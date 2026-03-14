"""Skill discovery for the Agent Skills standard.

This module provides functionality to discover, parse, and load skills
following the Agent Skills specification (agentskills.io).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger("framework.skills")


class SkillScope(Enum):
    """The scope/location of a skill."""

    PROJECT = "project"
    USER = "user"
    FRAMEWORK = "framework"


@dataclass
class Skill:
    """Represents a discovered skill."""

    name: str
    description: str
    location: Path
    base_dir: Path
    source_scope: SkillScope
    license: str | None = None
    compatibility: list[str] | None = None

    def __repr__(self) -> str:
        return f"Skill(name={self.name!r}, scope={self.source_scope.value})"


SKILL_DIR_NAMES = [".agents", ".hive"]
SKILL_SUBDIR = "skills"
SKILL_FILE = "SKILL.md"
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".env", ".tox"}
MAX_DEPTH = 4
MAX_DIRS = 2000


def parse_skill_file(skill_path: Path) -> dict[str, Any] | None:
    """Parse a SKILL.md file.

    Extracts YAML frontmatter and validates required fields.

    Args:
        skill_path: Path to SKILL.md

    Returns:
        Dictionary with skill metadata, or None if invalid
    """
    if not skill_path.exists():
        return None

    try:
        content = skill_path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("Failed to read skill file %s: %s", skill_path, e)
        return None

    if not content.startswith("---"):
        logger.warning("Skill file %s missing YAML frontmatter", skill_path)
        return None

    try:
        end_idx = content[3:].index("---") + 3
        frontmatter = content[3:end_idx].strip()
        body = content[end_idx + 3:].strip()
    except ValueError:
        logger.warning("Skill file %s has malformed YAML frontmatter", skill_path)
        return None

    yaml_data = _parse_yaml_frontmatter(frontmatter)
    if yaml_data is None:
        logger.warning("Failed to parse YAML in %s", skill_path)
        return None

    name = yaml_data.get("name")
    description = yaml_data.get("description")

    if not name:
        logger.warning("Skill %s missing required 'name' field", skill_path)
        return None

    if not description:
        logger.warning("Skill %s missing required 'description' field", skill_path)
        return None

    return {
        "name": name,
        "description": description,
        "license": yaml_data.get("license"),
        "compatibility": yaml_data.get("compatibility"),
        "metadata": yaml_data.get("metadata"),
        "allowed_tools": yaml_data.get("allowed_tools"),
        "body": body,
    }


def _parse_yaml_frontmatter(frontmatter: str) -> dict[str, Any] | None:
    """Parse YAML frontmatter with fallback for common issues."""
    try:
        import yaml
        return yaml.safe_load(frontmatter)
    except ImportError:
        pass

    try:
        data = {}
        for line in frontmatter.split("\n"):
            line = line.rstrip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            if value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            elif value.startswith("'") and value.endswith("'"):
                value = value[1:-1]
            data[key] = value
        return data if data else None
    except Exception:
        return None


def scan_directory_for_skills(
    root_dir: Path,
    scope: SkillScope,
    max_depth: int = MAX_DEPTH,
) -> list[Skill]:
    """Scan a directory for skills.

    Args:
        root_dir: Root directory to scan
        scope: The scope (project/user/framework) of this root
        max_depth: Maximum directory depth to scan

    Returns:
        List of discovered skills
    """
    skills = []
    dirs_scanned = 0

    if not root_dir.exists() or not root_dir.is_dir():
        return skills

    def _scan_recursive(current_dir: Path, depth: int) -> None:
        nonlocal dirs_scanned

        if depth > max_depth or dirs_scanned > MAX_DIRS:
            return

        try:
            entries = list(current_dir.iterdir())
        except PermissionError:
            return

        for entry in entries:
            if entry.name in SKIP_DIRS:
                continue

            if entry.is_dir():
                dirs_scanned += 1

                skill_file = entry / SKILL_FILE
                if skill_file.exists():
                    skill_data = parse_skill_file(skill_file)
                    if skill_data:
                        skill = Skill(
                            name=skill_data["name"],
                            description=skill_data["description"],
                            location=skill_file,
                            base_dir=entry,
                            source_scope=scope,
                            license=skill_data.get("license"),
                            compatibility=skill_data.get("compatibility"),
                        )
                        skills.append(skill)
                        logger.debug("Discovered skill: %s at %s", skill.name, skill.location)
                else:
                    _scan_recursive(entry, depth + 1)

    _scan_recursive(root_dir, 0)
    return skills


class SkillDiscovery:
    """Discovers and catalogs skills from various sources."""

    def __init__(
        self,
        project_path: Path | str | None = None,
        framework_path: Path | str | None = None,
    ):
        """Initialize skill discovery.

        Args:
            project_path: Path to the project. Defaults to current directory.
            framework_path: Path to framework skills. Auto-detected if None.
        """
        self._project_path = Path(project_path) if project_path else Path.cwd()
        self._framework_path = Path(framework_path) if framework_path else None

    @property
    def framework_path(self) -> Path | None:
        """Get the framework skills path."""
        if self._framework_path:
            return self._framework_path

        try:
            import framework
            framework_dir = Path(framework.__file__).parent
            defaults_path = framework_dir / "skills" / "defaults"
            if defaults_path.exists():
                return defaults_path
        except Exception:
            pass
        return None

    def get_skill_paths(self) -> dict[SkillScope, list[Path]]:
        """Get all skill search paths by scope.

        Returns:
            Dictionary mapping scope to list of paths to scan
        """
        paths: dict[SkillScope, list[Path]] = {
            SkillScope.PROJECT: [],
            SkillScope.USER: [],
            SkillScope.FRAMEWORK: [],
        }

        project_skills = self._project_path
        for dir_name in SKILL_DIR_NAMES:
            skill_dir = project_skills / dir_name / SKILL_SUBDIR
            if skill_dir.exists():
                paths[SkillScope.PROJECT].append(skill_dir)

        user_home = Path.home()
        for dir_name in SKILL_DIR_NAMES:
            user_skill_dir = user_home / dir_name / SKILL_SUBDIR
            if user_skill_dir.exists():
                paths[SkillScope.USER].append(user_skill_dir)

        fw_path = self.framework_path
        if fw_path:
            paths[SkillScope.FRAMEWORK].append(fw_path)

        return paths

    def scan(self) -> list[Skill]:
        """Scan all skill locations and return discovered skills.

        Returns:
            List of all discovered skills
        """
        all_skills = []

        for scope, paths in self.get_skill_paths().items():
            for path in paths:
                skills = scan_directory_for_skills(path, scope)
                all_skills.extend(skills)

        return all_skills

    def scan_project(self) -> list[Skill]:
        """Scan only project-level skills.

        Returns:
            List of project-level skills
        """
        skills = []
        paths = self.get_skill_paths()[SkillScope.PROJECT]
        for path in paths:
            skills.extend(scan_directory_for_skills(path, SkillScope.PROJECT))
        return skills

    def scan_user(self) -> list[Skill]:
        """Scan only user-level skills.

        Returns:
            List of user-level skills
        """
        skills = []
        paths = self.get_skill_paths()[SkillScope.USER]
        for path in paths:
            skills.extend(scan_directory_for_skills(path, SkillScope.USER))
        return skills

    def scan_framework(self) -> list[Skill]:
        """Scan only framework-level skills.

        Returns:
            List of framework-level skills
        """
        skills = []
        paths = self.get_skill_paths()[SkillScope.FRAMEWORK]
        for path in paths:
            skills.extend(scan_directory_for_skills(path, SkillScope.FRAMEWORK))
        return skills


def generate_skill_catalog(skills: list[Skill]) -> str:
    """Generate skill catalog XML for system prompt injection.

    Args:
        skills: List of skills to include in catalog

    Returns:
        XML-formatted skill catalog
    """
    if not skills:
        return "<available_skills></available_skills>"

    lines = ["<available_skills>"]
    for skill in skills:
        lines.append("  <skill>")
        lines.append(f"    <name>{_escape_xml(skill.name)}</name>")
        lines.append(f"    <description>{_escape_xml(skill.description)}</description>")
        lines.append(f"    <location>{_escape_xml(str(skill.location))}</location>")
        lines.append(f"    <scope>{skill.source_scope.value}</scope>")
        lines.append("  </skill>")
    lines.append("</available_skills>")

    return "\n".join(lines)


def _escape_xml(text: str) -> str:
    """Escape special XML characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
