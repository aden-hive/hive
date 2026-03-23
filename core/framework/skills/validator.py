"""Strict SKILL.md validation for contributor tooling (hive skill validate).

Unlike the lenient parser used at runtime, this module applies hard-error rules
that match the Agent Skills specification exactly. Intended for contributor
tooling, CI gates, and hive skill doctor.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from framework.skills.parser import _MAX_NAME_LENGTH, parse_skill_md


@dataclass
class ValidationResult:
    """Result of a strict SKILL.md validation run."""

    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_strict(path: Path) -> ValidationResult:
    """Run all strict checks against a SKILL.md file.

    Applies hard-error rules that go beyond the lenient runtime parser:
    - name must be explicit (no directory-name fallback)
    - YAML must parse without fixup
    - name/directory mismatch is an error, not a warning
    - empty body is an error
    - scripts must be executable

    Args:
        path: Path to the SKILL.md file to validate.

    Returns:
        ValidationResult with passed=True if no errors, plus any warnings.
    """
    errors: list[str] = []
    warnings: list[str] = []

    # 1. File exists and is readable
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ValidationResult(passed=False, errors=[f"File not found: {path}"])
    except PermissionError:
        return ValidationResult(passed=False, errors=[f"Permission denied reading: {path}"])
    except OSError as exc:
        return ValidationResult(passed=False, errors=[f"Cannot read file: {exc}"])

    # 2. File not empty
    if not content.strip():
        return ValidationResult(passed=False, errors=["File is empty."])

    # 3. YAML frontmatter present
    parts = content.split("---", 2)
    if len(parts) < 3:
        return ValidationResult(
            passed=False,
            errors=["Missing YAML frontmatter — wrap frontmatter with --- delimiters."],
        )

    raw_yaml = parts[1].strip()
    body = parts[2].strip()

    if not raw_yaml:
        return ValidationResult(
            passed=False,
            errors=["Frontmatter delimiters present but YAML block is empty."],
        )

    # 4. YAML parses WITHOUT fixup (strict: unquoted colons are an error)
    import yaml

    frontmatter: dict | None = None
    try:
        frontmatter = yaml.safe_load(raw_yaml)
    except yaml.YAMLError as exc:
        errors.append(
            f"YAML parse error: {exc}. "
            'Wrap values containing colons in quotes, e.g. description: "Use for: research".'
        )
        return ValidationResult(passed=False, errors=errors, warnings=warnings)

    if not isinstance(frontmatter, dict):
        return ValidationResult(
            passed=False,
            errors=["Frontmatter is not a YAML key-value mapping."],
        )

    # 5. description present and non-empty
    description = frontmatter.get("description")
    if not description or not str(description).strip():
        errors.append("Missing required field: 'description' must be present and non-empty.")

    # 6. name present and non-empty (no directory-name fallback in strict mode)
    name = frontmatter.get("name")
    if not name or not str(name).strip():
        errors.append(
            "Missing required field: 'name' must be present. "
            "Add 'name: your-skill-name' to the frontmatter."
        )
    else:
        name = str(name).strip()
        parent_dir_name = path.parent.name

        # 7. name length <= 64 chars
        if len(name) > _MAX_NAME_LENGTH:
            errors.append(
                f"Skill name '{name}' is {len(name)} characters — "
                f"maximum is {_MAX_NAME_LENGTH}. Shorten the name."
            )

        # 8. name matches parent directory (dot-namespace prefix allowed: hive.X with dir X)
        if name != parent_dir_name and not name.endswith(f".{parent_dir_name}"):
            errors.append(
                f"Name '{name}' does not match directory '{parent_dir_name}'. "
                f"Rename the directory to '{name}' or set name to '{parent_dir_name}'."
            )

    # 9. body non-empty
    if not body:
        errors.append(
            "Skill body (instructions) is empty. "
            "Add markdown instructions after the closing --- delimiter."
        )

    # 10. license present — warning only
    if not frontmatter.get("license"):
        warnings.append("No 'license' field — consider adding a license (e.g. MIT, Apache-2.0).")

    # 11. Scripts in scripts/ exist and are executable
    base_dir = path.parent
    scripts_dir = base_dir / "scripts"
    if scripts_dir.is_dir():
        for script_path in sorted(scripts_dir.iterdir()):
            if script_path.is_file():
                if not os.access(script_path, os.X_OK):
                    errors.append(
                        f"Script not executable: {script_path.name}. "
                        f"Run: chmod +x {script_path}"
                    )

    # 12. allowed-tools entries are non-empty strings — warning if malformed
    allowed_tools = frontmatter.get("allowed-tools")
    if allowed_tools is not None:
        if not isinstance(allowed_tools, list):
            warnings.append("'allowed-tools' should be a list of strings.")
        else:
            for tool in allowed_tools:
                if not isinstance(tool, str) or not tool.strip():
                    warnings.append(
                        f"'allowed-tools' entry {tool!r} is not a non-empty string."
                    )

    # 13. compatibility is a list of strings — error if malformed
    compatibility = frontmatter.get("compatibility")
    if compatibility is not None:
        if not isinstance(compatibility, list):
            errors.append("'compatibility' must be a list of strings.")
        else:
            for item in compatibility:
                if not isinstance(item, str):
                    errors.append(
                        f"'compatibility' entry {item!r} is not a string."
                    )

    # 14. metadata is a dict — error if malformed
    metadata = frontmatter.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        errors.append("'metadata' must be a YAML mapping (dict), not a scalar or list.")

    return ValidationResult(
        passed=len(errors) == 0,
        errors=errors,
        warnings=warnings,
    )
