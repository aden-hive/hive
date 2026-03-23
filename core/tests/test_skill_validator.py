"""Tests for strict SKILL.md validation (hive skill validate).

One test per strict check — happy path plus each individual failure mode.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from framework.skills.validator import validate_strict


def _write_skill(tmp_path: Path, content: str, dir_name: str = "my-skill") -> Path:
    """Write a SKILL.md in a named subdirectory and return the path."""
    skill_dir = tmp_path / dir_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(content, encoding="utf-8")
    return skill_md


_VALID_CONTENT = """\
---
name: my-skill
description: A test skill for validation.
version: 0.1.0
license: MIT
compatibility:
  - claude-code
  - hive
metadata:
  tags: []
---

## Instructions

Do the thing properly.
"""


class TestHappyPath:
    def test_valid_skill_passes(self, tmp_path):
        path = _write_skill(tmp_path, _VALID_CONTENT)
        result = validate_strict(path)
        assert result.passed is True
        assert result.errors == []

    def test_namespace_prefix_name_allowed(self, tmp_path):
        """hive.my-skill with directory my-skill is valid."""
        content = """\
---
name: hive.my-skill
description: A namespaced skill.
license: MIT
---

## Body
"""
        path = _write_skill(tmp_path, content, dir_name="my-skill")
        result = validate_strict(path)
        assert result.passed is True

    def test_warning_on_missing_license(self, tmp_path):
        content = """\
---
name: my-skill
description: No license field.
---

## Body
"""
        path = _write_skill(tmp_path, content)
        result = validate_strict(path)
        assert result.passed is True
        assert any("license" in w.lower() for w in result.warnings)


class TestCheck1FileExists:
    def test_error_on_missing_file(self, tmp_path):
        path = tmp_path / "nonexistent" / "SKILL.md"
        result = validate_strict(path)
        assert result.passed is False
        assert any("not found" in e.lower() for e in result.errors)


class TestCheck2FileNotEmpty:
    def test_error_on_empty_file(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        path = skill_dir / "SKILL.md"
        path.write_text("   \n", encoding="utf-8")
        result = validate_strict(path)
        assert result.passed is False
        assert any("empty" in e.lower() for e in result.errors)


class TestCheck3FrontmatterPresent:
    def test_error_on_missing_delimiters(self, tmp_path):
        path = _write_skill(tmp_path, "name: my-skill\ndescription: no delimiters\n")
        result = validate_strict(path)
        assert result.passed is False
        assert any("frontmatter" in e.lower() or "---" in e for e in result.errors)


class TestCheck4YamlNoFixup:
    def test_error_on_yaml_requiring_fixup(self, tmp_path):
        """Unquoted colon in value — lenient parser accepts, strict rejects."""
        content = """\
---
name: my-skill
description: Use for: research tasks
---

## Body
"""
        path = _write_skill(tmp_path, content)
        result = validate_strict(path)
        assert result.passed is False
        assert any("YAML" in e or "parse" in e.lower() for e in result.errors)

    def test_quoted_colon_passes(self, tmp_path):
        content = """\
---
name: my-skill
description: "Use for: research tasks"
license: MIT
---

## Body
"""
        path = _write_skill(tmp_path, content)
        result = validate_strict(path)
        assert result.passed is True


class TestCheck5Description:
    def test_error_on_missing_description(self, tmp_path):
        content = """\
---
name: my-skill
license: MIT
---

## Body
"""
        path = _write_skill(tmp_path, content)
        result = validate_strict(path)
        assert result.passed is False
        assert any("description" in e.lower() for e in result.errors)

    def test_error_on_empty_description(self, tmp_path):
        content = """\
---
name: my-skill
description: ""
license: MIT
---

## Body
"""
        path = _write_skill(tmp_path, content)
        result = validate_strict(path)
        assert result.passed is False


class TestCheck6NamePresent:
    def test_error_on_missing_name(self, tmp_path):
        content = """\
---
description: A skill without a name.
license: MIT
---

## Body
"""
        path = _write_skill(tmp_path, content)
        result = validate_strict(path)
        assert result.passed is False
        assert any("name" in e.lower() for e in result.errors)


class TestCheck7NameLength:
    def test_error_on_name_too_long(self, tmp_path):
        long_name = "a" * 65
        skill_dir = tmp_path / long_name
        skill_dir.mkdir(parents=True)
        content = f"---\nname: {long_name}\ndescription: Too long.\nlicense: MIT\n---\n\n## Body\n"
        path = skill_dir / "SKILL.md"
        path.write_text(content, encoding="utf-8")

        result = validate_strict(path)
        assert result.passed is False
        assert any("64" in e or "characters" in e.lower() for e in result.errors)

    def test_exactly_64_chars_passes(self, tmp_path):
        name = "a" * 64
        skill_dir = tmp_path / name
        skill_dir.mkdir(parents=True)
        content = f"---\nname: {name}\ndescription: Exactly 64.\nlicense: MIT\n---\n\n## Body\n"
        path = skill_dir / "SKILL.md"
        path.write_text(content, encoding="utf-8")

        result = validate_strict(path)
        # May have other warnings but should not error on length
        assert not any("64" in e or "characters" in e.lower() for e in result.errors)


class TestCheck8NameDirectoryMatch:
    def test_error_on_name_dir_mismatch(self, tmp_path):
        content = """\
---
name: other-skill
description: Wrong name.
license: MIT
---

## Body
"""
        # Directory is my-skill but name is other-skill
        path = _write_skill(tmp_path, content, dir_name="my-skill")
        result = validate_strict(path)
        assert result.passed is False
        assert any("other-skill" in e or "my-skill" in e for e in result.errors)

    def test_exact_match_passes(self, tmp_path):
        content = """\
---
name: my-skill
description: Exact match.
license: MIT
---

## Body
"""
        path = _write_skill(tmp_path, content, dir_name="my-skill")
        result = validate_strict(path)
        assert result.passed is True

    def test_dot_namespace_prefix_passes(self, tmp_path):
        """hive.my-skill with dir my-skill is valid (namespace prefix)."""
        content = """\
---
name: org.my-skill
description: Namespaced.
license: MIT
---

## Body
"""
        path = _write_skill(tmp_path, content, dir_name="my-skill")
        result = validate_strict(path)
        # Should not error on name/dir mismatch for namespace prefix
        assert not any("my-skill" in e and "other" in e for e in result.errors)
        # Check no dir mismatch error specifically
        name_mismatch_errors = [e for e in result.errors if "my-skill" in e and "org.my-skill" in e]
        assert len(name_mismatch_errors) == 0


class TestCheck9BodyNotEmpty:
    def test_error_on_empty_body(self, tmp_path):
        content = """\
---
name: my-skill
description: No body.
license: MIT
---
"""
        path = _write_skill(tmp_path, content)
        result = validate_strict(path)
        assert result.passed is False
        assert any("body" in e.lower() or "instructions" in e.lower() for e in result.errors)


class TestCheck11Scripts:
    def test_error_on_non_executable_script(self, tmp_path):
        path = _write_skill(tmp_path, _VALID_CONTENT)
        scripts_dir = path.parent / "scripts"
        scripts_dir.mkdir()
        script = scripts_dir / "run.sh"
        script.write_text("#!/bin/sh\necho hi")
        # Ensure NOT executable
        script.chmod(0o644)

        result = validate_strict(path)
        assert result.passed is False
        assert any("executable" in e.lower() for e in result.errors)

    def test_passes_with_executable_script(self, tmp_path):
        path = _write_skill(tmp_path, _VALID_CONTENT)
        scripts_dir = path.parent / "scripts"
        scripts_dir.mkdir()
        script = scripts_dir / "run.sh"
        script.write_text("#!/bin/sh\necho hi")
        script.chmod(0o755)

        result = validate_strict(path)
        assert result.passed is True


class TestCheck12AllowedTools:
    def test_warning_on_malformed_allowed_tools(self, tmp_path):
        content = """\
---
name: my-skill
description: Skill with bad tools.
license: MIT
allowed-tools: "not a list"
---

## Body
"""
        path = _write_skill(tmp_path, content)
        result = validate_strict(path)
        assert any("allowed-tools" in w.lower() for w in result.warnings)

    def test_valid_allowed_tools_no_warning(self, tmp_path):
        content = """\
---
name: my-skill
description: Valid tools list.
license: MIT
allowed-tools:
  - web_search
  - file_read
---

## Body
"""
        path = _write_skill(tmp_path, content)
        result = validate_strict(path)
        assert not any("allowed-tools" in w.lower() for w in result.warnings)


class TestCheck13Compatibility:
    def test_error_on_non_list_compatibility(self, tmp_path):
        content = """\
---
name: my-skill
description: Bad compat.
license: MIT
compatibility: "claude-code"
---

## Body
"""
        path = _write_skill(tmp_path, content)
        result = validate_strict(path)
        assert result.passed is False
        assert any("compatibility" in e.lower() for e in result.errors)

    def test_valid_compatibility_passes(self, tmp_path):
        content = """\
---
name: my-skill
description: Good compat.
license: MIT
compatibility:
  - claude-code
  - hive
---

## Body
"""
        path = _write_skill(tmp_path, content)
        result = validate_strict(path)
        assert result.passed is True


class TestCheck14Metadata:
    def test_error_on_non_dict_metadata(self, tmp_path):
        content = """\
---
name: my-skill
description: Bad metadata.
license: MIT
metadata: "not a dict"
---

## Body
"""
        path = _write_skill(tmp_path, content)
        result = validate_strict(path)
        assert result.passed is False
        assert any("metadata" in e.lower() for e in result.errors)

    def test_valid_metadata_passes(self, tmp_path):
        content = """\
---
name: my-skill
description: Good metadata.
license: MIT
metadata:
  tags:
    - research
---

## Body
"""
        path = _write_skill(tmp_path, content)
        result = validate_strict(path)
        assert result.passed is True
