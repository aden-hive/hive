"""Skill discovery — scans all scope locations and parses SKILL.md files.

Implements PRD §4.1 (discovery) and §4.2 (parsing) of the Agent Skills standard.
Precedence (highest first): project/.hive > project/.agents > user/.hive >
user/.agents > framework/defaults.  Within the same name, first wins.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from framework.skills.models import SkillEntry, SkillScope, TrustStatus

logger = logging.getLogger(__name__)

# Directories to skip when scanning (PRD §4.1)
_SKIP_DIRS = frozenset({".git", "node_modules", "__pycache__", ".venv", ".env"})

_MAX_DEPTH = 4
_MAX_DIRS_PER_SCOPE = 2000


def _framework_defaults_dir() -> Path:
    """Return the framework built-in defaults directory."""
    return Path(__file__).parent / "defaults"


class SkillDiscovery:
    """Discovers skills across all scopes per the Agent Skills standard."""

    def discover(self, project_dir: Path | None) -> list[SkillEntry]:
        """Scan all scope locations and return deduplicated, ordered skill list.

        Args:
            project_dir: Root of the current project (for project-scope scan).
                         Pass None to skip project-scope discovery.

        Returns:
            Skills in precedence order; project > user > framework.
            Project-scope skills are marked PENDING_CONSENT.
            Name collisions are resolved deterministically (first wins) with a warning.
        """
        scan_locations: list[tuple[SkillScope, Path]] = []

        if project_dir is not None:
            scan_locations += [
                (SkillScope.PROJECT, project_dir / ".hive" / "skills"),
                (SkillScope.PROJECT, project_dir / ".agents" / "skills"),
            ]

        scan_locations += [
            (SkillScope.USER, Path.home() / ".hive" / "skills"),
            (SkillScope.USER, Path.home() / ".agents" / "skills"),
            (SkillScope.FRAMEWORK, _framework_defaults_dir()),
        ]

        seen_names: dict[str, SkillEntry] = {}  # name -> first (highest precedence) entry

        for scope, root in scan_locations:
            if not root.is_dir():
                continue
            for entry in self._scan_scope(root, scope):
                if entry.name in seen_names:
                    winner = seen_names[entry.name]
                    logger.warning(
                        "skill_collision: name=%s winner=%s (scope=%s) skipped=%s (scope=%s)",
                        entry.name,
                        winner.location,
                        winner.source_scope,
                        entry.location,
                        entry.source_scope,
                    )
                else:
                    seen_names[entry.name] = entry

        return list(seen_names.values())

    def _scan_scope(self, root: Path, scope: SkillScope) -> list[SkillEntry]:
        """Walk a single skill root directory, parsing each SKILL.md found."""
        entries: list[SkillEntry] = []
        dirs_visited = 0

        # BFS with depth tracking
        queue: list[tuple[Path, int]] = [(root, 0)]
        while queue:
            current, depth = queue.pop(0)
            dirs_visited += 1
            if dirs_visited > _MAX_DIRS_PER_SCOPE:
                logger.warning(
                    "skill_scan: max dirs (%d) reached in scope=%s root=%s",
                    _MAX_DIRS_PER_SCOPE,
                    scope,
                    root,
                )
                break

            skill_md = current / "SKILL.md"
            if skill_md.is_file():
                entry = _parse_skill_md(skill_md, scope)
                if entry is not None:
                    entries.append(entry)
                # Don't descend into skill directories
                continue

            if depth < _MAX_DEPTH:
                try:
                    for child in sorted(current.iterdir()):
                        if child.is_dir() and child.name not in _SKIP_DIRS:
                            queue.append((child, depth + 1))
                except PermissionError:
                    pass

        return entries


def _parse_skill_md(path: Path, scope: SkillScope) -> SkillEntry | None:
    """Parse a SKILL.md file, returning a SkillEntry or None on failure.

    Lenient validation per PRD §4.2:
    - Skip only if description is missing/empty or YAML is unparseable.
    - Warn (but load) on name/directory mismatch or name > 64 chars.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        logger.error("skill_parse_error: path=%s error=%s", path, e)
        return None

    frontmatter, _ = _split_frontmatter(text)
    if frontmatter is None:
        logger.error(
            "skill_parse_error: path=%s error=no YAML frontmatter found", path
        )
        return None

    data = _load_yaml(frontmatter, path)
    if data is None:
        return None  # already logged

    if not isinstance(data, dict):
        logger.error("skill_parse_error: path=%s error=frontmatter is not a mapping", path)
        return None

    # Required: description
    description = data.get("description", "")
    if not description or not str(description).strip():
        logger.error(
            "skill_parse_error: path=%s error=description missing or empty — skipping",
            path,
        )
        return None

    # Required: name (warn if missing, fall back to directory name)
    name = data.get("name", "")
    if not name or not str(name).strip():
        logger.warning(
            "skill_parse_warning: path=%s warning=name missing, using directory name",
            path,
        )
        name = path.parent.name

    name = str(name).strip()
    description = str(description).strip()

    # Non-blocking warnings
    if len(name) > 64:
        logger.warning(
            "skill_parse_warning: path=%s warning=name exceeds 64 chars (%d)",
            path,
            len(name),
        )
    if name != path.parent.name:
        logger.warning(
            "skill_parse_warning: path=%s warning=name=%r does not match directory=%r",
            path,
            name,
            path.parent.name,
        )

    # Optional fields
    license_val = data.get("license")
    compatibility = _ensure_list(data.get("compatibility", []))
    allowed_tools = _ensure_list(data.get("allowed-tools", []))
    metadata = data.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}

    trust = (
        TrustStatus.PENDING_CONSENT
        if scope == SkillScope.PROJECT
        else TrustStatus.TRUSTED
    )

    return SkillEntry(
        name=name,
        description=description,
        location=path.resolve(),
        base_dir=path.parent.resolve(),
        source_scope=scope,
        trust_status=trust,
        license=str(license_val) if license_val else None,
        compatibility=compatibility,
        allowed_tools=allowed_tools,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# YAML helpers
# ---------------------------------------------------------------------------


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    """Split SKILL.md text into (frontmatter, body).

    Returns (None, full_text) if no valid frontmatter delimiters found.
    Strips a leading BOM and any leading blank lines before the opening ``---``
    (a common heredoc artifact).
    """
    # Strip BOM and leading blank lines — heredoc and some editors add them
    text = text.lstrip("\ufeff\r\n")

    if not text.startswith("---"):
        return None, text

    # Find closing ---
    rest = text[3:]
    # Allow --- or ---\n as opener
    if rest.startswith("\n"):
        rest = rest[1:]
    elif rest.startswith("\r\n"):
        rest = rest[2:]

    end = re.search(r"^---\s*$", rest, re.MULTILINE)
    if end is None:
        return None, text

    frontmatter = rest[: end.start()]
    body = rest[end.end() :]
    if body.startswith("\n"):
        body = body[1:]

    return frontmatter, body


def _load_yaml(frontmatter_text: str, path: Path) -> dict | None:
    """Parse YAML frontmatter with AS-15 colon-fixup fallback."""
    try:
        import yaml
    except ImportError:
        logger.error(
            "skill_parse_error: PyYAML is not installed; cannot parse %s", path
        )
        return None

    # First attempt: parse as-is
    try:
        return yaml.safe_load(frontmatter_text)
    except yaml.YAMLError:
        pass

    # Second attempt: AS-15 colon-value fixup
    fixed = _fix_unquoted_colon_values(frontmatter_text)
    try:
        result = yaml.safe_load(fixed)
        logger.warning(
            "skill_parse_warning: path=%s warning=needed colon-fixup to parse YAML",
            path,
        )
        return result
    except yaml.YAMLError as e:
        logger.error(
            "skill_parse_error: path=%s error=YAML unparseable even after fixup: %s",
            path,
            e,
        )
        return None


def _fix_unquoted_colon_values(text: str) -> str:
    """Wrap string values that contain unquoted colons in double quotes.

    Handles the common case of ``description: Multi-step research: finds sources``.
    Only touches lines that are a simple ``key: value`` mapping and whose stripped
    value is not already quoted or a YAML block/flow indicator character.
    """
    lines = text.splitlines()
    fixed = []
    for line in lines:
        # Capture key + everything after the colon separator
        m = re.match(r'^(\s*[\w][\w\-]*\s*:\s*)(.*\S.*)$', line)
        if m:
            value = m.group(2).strip()
            # Only fix if value has a colon AND is not already quoted/structured
            if ":" in value and not re.match(r'^["\'\[\{>|#]', value):
                escaped = value.replace('"', '\\"')
                line = m.group(1) + f'"{escaped}"'
        fixed.append(line)
    return "\n".join(fixed)


def _ensure_list(value: object) -> list[str]:
    """Coerce a YAML value to a list of strings."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [value]
    return []
