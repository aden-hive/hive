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
        logger.error("Failed to read %s: %s", path, exc)
        return None

    if not content.strip():
        logger.error("Empty SKILL.md: %s", path)
        return None

    # Split on --- delimiters (first two occurrences)
    parts = content.split("---", 2)
    if len(parts) < 3:
        logger.error("SKILL.md missing YAML frontmatter delimiters (---): %s", path)
        return None

    # parts[0] is content before first --- (should be empty or whitespace)
    # parts[1] is the YAML frontmatter
    # parts[2] is the markdown body
    raw_yaml = parts[1].strip()
    body = parts[2].strip()

    if not raw_yaml:
        logger.error("Empty YAML frontmatter in %s", path)
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
            logger.warning("Fixed YAML parse issues in %s (unquoted colons)", path)
        except yaml.YAMLError as exc:
            logger.error("Unparseable YAML in %s: %s", path, exc)
            return None

    if not isinstance(frontmatter, dict):
        logger.error("YAML frontmatter is not a mapping in %s", path)
        return None

    # Required: description
    description = frontmatter.get("description")
    if not description or not str(description).strip():
        logger.error("Missing or empty 'description' in %s — skipping skill", path)
        return None

    # Required: name (fallback to parent directory name)
    name = frontmatter.get("name")
    parent_dir_name = path.parent.name
    if not name or not str(name).strip():
        name = parent_dir_name
        logger.warning("Missing 'name' in %s — using directory name '%s'", path, name)
    else:
        name = str(name).strip()

    # Lenient warnings
    if len(name) > _MAX_NAME_LENGTH:
        logger.warning("Skill name exceeds %d chars in %s: '%s'", _MAX_NAME_LENGTH, path, name)

    if name != parent_dir_name and not name.endswith(f".{parent_dir_name}"):
        logger.warning(
            "Skill name '%s' doesn't match parent directory '%s' in %s",
            name,
            parent_dir_name,
            path,
        )

    return ParsedSkill(
        name=name,
        description=str(description).strip(),
        location=str(path.resolve()),
        base_dir=str(path.parent.resolve()),
        source_scope=source_scope,
        body=body,
        license=frontmatter.get("license"),
        compatibility=frontmatter.get("compatibility"),
        metadata=frontmatter.get("metadata"),
        allowed_tools=frontmatter.get("allowed-tools"),
    )
