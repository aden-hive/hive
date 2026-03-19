"""Tests for SKILL.md parser."""

from pathlib import Path

import pytest

from framework.skills.parser import parse_skill_md


@pytest.fixture
def tmp_skill(tmp_path):
    """Helper to create a SKILL.md file and return its path."""

    def _create(content: str, dir_name: str = "my-skill") -> Path:
        skill_dir = tmp_path / dir_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(content, encoding="utf-8")
        return skill_md

    return _create


class TestParseSkillMd:
    def test_happy_path(self, tmp_skill):
        content = """---
name: my-skill
description: A test skill for unit testing.
license: MIT
---

## Instructions

Do the thing.
"""
        result = parse_skill_md(tmp_skill(content), source_scope="project")
        assert result is not None
        assert result.name == "my-skill"
        assert result.description == "A test skill for unit testing."
        assert result.license == "MIT"
        assert result.source_scope == "project"
        assert "Do the thing." in result.body

    def test_missing_description_returns_none(self, tmp_skill):
        content = """---
name: no-desc
---

Body here.
"""
        result = parse_skill_md(tmp_skill(content, "no-desc"))
        assert result is None

    def test_missing_name_uses_directory(self, tmp_skill):
        content = """---
description: Skill without a name field.
---

Body.
"""
        result = parse_skill_md(tmp_skill(content, "fallback-dir"))
        assert result is not None
        assert result.name == "fallback-dir"

    def test_empty_file_returns_none(self, tmp_skill):
        result = parse_skill_md(tmp_skill("", "empty"))
        assert result is None

    def test_no_frontmatter_delimiters_returns_none(self, tmp_skill):
        content = "Just plain text without YAML frontmatter."
        result = parse_skill_md(tmp_skill(content, "no-yaml"))
        assert result is None

    def test_unparseable_yaml_returns_none(self, tmp_skill):
        content = """---
name: [invalid yaml
  - broken: {{
---

Body.
"""
        result = parse_skill_md(tmp_skill(content, "bad-yaml"))
        assert result is None

    def test_unquoted_colon_fixup(self, tmp_skill):
        content = """---
name: colon-test
description: Use for: research tasks
---

Body.
"""
        result = parse_skill_md(tmp_skill(content, "colon-test"))
        assert result is not None
        assert "research tasks" in result.description

    def test_long_name_warns_but_loads(self, tmp_skill):
        long_name = "a" * 100
        content = f"""---
name: {long_name}
description: A skill with an excessively long name.
---

Body.
"""
        result = parse_skill_md(tmp_skill(content, "long-name"))
        assert result is not None
        assert result.name == long_name

    def test_name_mismatch_warns_but_loads(self, tmp_skill):
        content = """---
name: different-name
description: Name doesn't match directory.
---

Body.
"""
        result = parse_skill_md(tmp_skill(content, "actual-dir"))
        assert result is not None
        assert result.name == "different-name"

    def test_optional_fields(self, tmp_skill):
        content = """---
name: full-skill
description: Skill with all optional fields.
license: Apache-2.0
compatibility:
  - claude-code
  - cursor
metadata:
  author: tester
  version: "1.0"
allowed-tools:
  - web_search
  - read_file
---

Instructions here.
"""
        result = parse_skill_md(tmp_skill(content, "full-skill"))
        assert result is not None
        assert result.license == "Apache-2.0"
        assert result.compatibility == ["claude-code", "cursor"]
        assert result.metadata == {"author": "tester", "version": "1.0"}
        assert result.allowed_tools == ["web_search", "read_file"]

    def test_body_extraction(self, tmp_skill):
        content = """---
name: body-test
description: Test body extraction.
---

## Step 1

Do this first.

## Step 2

Then do this.
"""
        result = parse_skill_md(tmp_skill(content, "body-test"))
        assert result is not None
        assert "## Step 1" in result.body
        assert "## Step 2" in result.body
        assert "Do this first." in result.body

    def test_location_is_absolute(self, tmp_skill):
        content = """---
name: abs-path
description: Check absolute path.
---

Body.
"""
        path = tmp_skill(content, "abs-path")
        result = parse_skill_md(path)
        assert result is not None
        assert Path(result.location).is_absolute()
        assert Path(result.base_dir).is_absolute()

    def test_nonexistent_file_returns_none(self, tmp_path):
        result = parse_skill_md(tmp_path / "nonexistent" / "SKILL.md")
        assert result is None
