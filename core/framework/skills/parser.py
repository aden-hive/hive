"""SKILL.md parser — extracts YAML frontmatter and markdown body.

Parses SKILL.md files per the Agent Skills standard (agentskills.io/specification).
Lenient validation: warns on non-critical issues, skips only on missing description
or completely unparseable YAML.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from framework.skills.skill_errors import SkillErrorCode, log_skill_error

logger = logging.getLogger(__name__)

# Maximum name length before a warning is logged
_MAX_NAME_LENGTH = 64


@dataclass
class ParsedSkill:
    """In-memory representation of a parsed SKILL.md file."""

    name: str
    description: str
    location: str  # absolute path to SKILL.md
    base_dir: str  # parent directory of SKILL.md
    source_scope: str  # "project", "user", or "framework"
    body: str  # markdown body after closing ---

    # Optional frontmatter fields
    license: str | None = None
    compatibility: list[str] | None = None
    metadata: dict[str, Any] | None = None
    allowed_tools: list[str] | None = None
    # List of queen phases in which this skill appears in the catalog.
    # None = visible in all phases. Example: ["planning", "building"]
    # hides a framework-authoring skill from the INDEPENDENT/DM prompt.
    visibility: list[str] | None = None


def _try_fix_yaml(raw: str) -> str:
    """Attempt to fix common YAML issues (unquoted colon values).

    Some SKILL.md files written for other clients may contain unquoted
    values with colons, e.g. ``description: Use for: research tasks``.
    This wraps such values in quotes as a best-effort fixup.
    """
    lines = raw.split("\n")
    fixed = []
    for line in lines:
        # Match "key: value" where value contains an unquoted colon
        m = re.match(r"^(\s*\w[\w-]*:\s*)(.+)$", line)
        if m:
            key_part, value_part = m.group(1), m.group(2)
            # If value contains a colon and isn't already quoted
            if ":" in value_part and not (value_part.startswith('"') or value_part.startswith("'")):
                value_part = f'"{value_part}"'
            fixed.append(f"{key_part}{value_part}")
        else:
            fixed.append(line)
    return "\n".join(fixed)


def parse_skill_md(path: Path, source_scope: str = "project") -> ParsedSkill | None:
    """Parse a SKILL.md file into a ParsedSkill record.

    Args:
        path: Absolute path to the SKILL.md file.
        source_scope: One of "project", "user", or "framework".

    Returns:
        ParsedSkill on success, None if the file is unparseable or
        missing required fields (description).
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        log_skill_error(
            logger,
            "error",
            SkillErrorCode.SKILL_ACTIVATION_FAILED,
            what=f"Failed to read '{path}'",
            why=str(exc),
            fix="Check the file exists and has read permissions.",
        )
        return None

    if not content.strip():
        log_skill_error(
            logger,
            "error",
            SkillErrorCode.SKILL_PARSE_ERROR,
            what=f"Invalid SKILL.md at '{path}'",
            why="The file exists but contains no content.",
            fix="Add valid YAML frontmatter and a markdown body to the SKILL.md.",
        )
        return None

    # Split on --- delimiters (first two occurrences)
    parts = content.split("---", 2)
    if len(parts) < 3:
        log_skill_error(
            logger,
            "error",
            SkillErrorCode.SKILL_PARSE_ERROR,
            what=f"Invalid SKILL.md at '{path}'",
            why="Missing YAML frontmatter (---).",
            fix="Wrap the frontmatter with --- on its own line at the top and bottom.",
        )
        return None

    # parts[0] is content before first --- (should be empty or whitespace)
    # parts[1] is the YAML frontmatter
    # parts[2] is the markdown body
    raw_yaml = parts[1].strip()
    body = parts[2].strip()

    if not raw_yaml:
        log_skill_error(
            logger,
            "error",
            SkillErrorCode.SKILL_PARSE_ERROR,
            what=f"Invalid SKILL.md at '{path}'",
            why="The --- delimiters are present but the YAML block is empty.",
            fix="Add at least 'name' and 'description' fields to the frontmatter.",
        )
        return None

    # Parse YAML
    import yaml

    frontmatter: dict[str, Any] | None = None
    try:
        frontmatter = yaml.safe_load(raw_yaml)
    except yaml.YAMLError:
        # Fallback: try fixing unquoted colon values
        try:
            fixed = _try_fix_yaml(raw_yaml)
            frontmatter = yaml.safe_load(fixed)
            log_skill_error(
                logger,
                "warning",
                SkillErrorCode.SKILL_YAML_FIXUP,
                what=f"Auto-fixed YAML in '{path}'",
                why="Unquoted colon values detected in frontmatter.",
                fix='Wrap values containing colons in quotes e.g. description: "Use for: research"',
            )
        except yaml.YAMLError as exc:
            log_skill_error(
                logger,
                "error",
                SkillErrorCode.SKILL_PARSE_ERROR,
                what=f"Invalid SKILL.md at '{path}'",
                why=str(exc),
                fix="Validate the YAML frontmatter at https://yaml-online-parser.appspot.com/",
            )
            return None

    if not isinstance(frontmatter, dict):
        log_skill_error(
            logger,
            "error",
            SkillErrorCode.SKILL_PARSE_ERROR,
            what=f"Invalid SKILL.md at '{path}'",
            why="YAML frontmatter is not a key-value mapping.",
            fix="Ensure the frontmatter is valid YAML with key: value pairs.",
        )
        return None

    # Required: description
    description = frontmatter.get("description")
    if not description or not str(description).strip():
        log_skill_error(
            logger,
            "error",
            SkillErrorCode.SKILL_MISSING_DESCRIPTION,
            what=f"Missing 'description' in '{path}'",
            why="The 'description' field is required but is absent or empty.",
            fix="Add a non-empty 'description' field to the YAML frontmatter.",
        )
        return None

    # Required: name (fallback to parent directory name)
    name = frontmatter.get("name")
    parent_dir_name = path.parent.name
    if not name or not str(name).strip():
        name = parent_dir_name
        log_skill_error(
            logger,
            "warning",
            SkillErrorCode.SKILL_NAME_MISMATCH,
            what=f"Missing 'name' in '{path}' — using directory name '{name}'",
            why="The 'name' field is absent from the YAML frontmatter.",
            fix=f"Add 'name: {name}' to the frontmatter to make this explicit.",
        )
    else:
        name = str(name).strip()

    # Lenient warnings
    if len(name) > _MAX_NAME_LENGTH:
        logger.warning("Skill name exceeds %d chars in %s: '%s'", _MAX_NAME_LENGTH, path, name)

    if name != parent_dir_name and not name.endswith(f".{parent_dir_name}"):
        log_skill_error(
            logger,
            "warning",
            SkillErrorCode.SKILL_NAME_MISMATCH,
            what=f"Name mismatch in '{path}'",
            why=f"Skill name '{name}' doesn't match directory '{parent_dir_name}'.",
            fix=f"Rename the directory to '{name}' or set name to '{parent_dir_name}'.",
        )

    # Coerce compatibility / allowed-tools to list[str] — many SKILL.md files
    # in the wild use a plain string instead of a YAML list.
    raw_compat = frontmatter.get("compatibility")
    if isinstance(raw_compat, str):
        raw_compat = [raw_compat]
    raw_tools = frontmatter.get("allowed-tools")
    if isinstance(raw_tools, str):
        raw_tools = [raw_tools]
    # `visibility` lives under `metadata.visibility` so it stays inside
    # the open `metadata` map (the skill-file schema used by the IDE
    # and other tooling only allows a fixed set of top-level keys).
    raw_metadata = frontmatter.get("metadata")
    raw_visibility: Any = None
    if isinstance(raw_metadata, dict):
        raw_visibility = raw_metadata.get("visibility")
    if isinstance(raw_visibility, str):
        raw_visibility = [raw_visibility]
    if isinstance(raw_visibility, list):
        raw_visibility = [str(v).strip() for v in raw_visibility if str(v).strip()] or None
    else:
        raw_visibility = None

    return ParsedSkill(
        name=name,
        description=str(description).strip(),
        location=str(path.resolve()),
        base_dir=str(path.parent.resolve()),
        source_scope=source_scope,
        body=body,
        license=frontmatter.get("license"),
        compatibility=raw_compat,
        metadata=frontmatter.get("metadata"),
        allowed_tools=raw_tools,
        visibility=raw_visibility,
    )
