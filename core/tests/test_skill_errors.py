"""Tests for skill system structured error codes and diagnostics."""

from __future__ import annotations

import logging

from framework.skills.skill_errors import (
    SkillError,
    SkillErrorCode,
    log_skill_error,
)


class TestSkillErrorCode:
    def test_all_codes_defined(self):
        codes = {e.value for e in SkillErrorCode}
        assert "SKILL_NOT_FOUND" in codes
        assert "SKILL_PARSE_ERROR" in codes
        assert "SKILL_ACTIVATION_FAILED" in codes
        assert "SKILL_MISSING_DESCRIPTION" in codes
        assert "SKILL_YAML_FIXUP" in codes
        assert "SKILL_NAME_MISMATCH" in codes
        assert "SKILL_COLLISION" in codes


class TestSkillError:
    def test_code_stored(self):
        err = SkillError(
            code=SkillErrorCode.SKILL_NOT_FOUND,
            what="Skill 'my-skill' not found",
            why="Not in catalog",
            fix="Check discovery paths",
        )
        assert err.code == SkillErrorCode.SKILL_NOT_FOUND

    def test_message_format(self):
        err = SkillError(
            code=SkillErrorCode.SKILL_MISSING_DESCRIPTION,
            what="Missing description in '/path/SKILL.md'",
            why="The description field is absent",
            fix="Add a description field to the frontmatter",
        )
        expected = (
            "[SKILL_MISSING_DESCRIPTION]\n"
            "What failed: Missing description in '/path/SKILL.md'\n"
            "Why: The description field is absent\n"
            "Fix: Add a description field to the frontmatter"
        )
        assert str(err) == expected

    def test_is_exception(self):
        err = SkillError(
            code=SkillErrorCode.SKILL_PARSE_ERROR,
            what="Parse failed",
            why="Invalid YAML",
            fix="Fix the YAML",
        )
        assert isinstance(err, Exception)

    def test_what_why_fix_attributes(self):
        err = SkillError(
            code=SkillErrorCode.SKILL_COLLISION,
            what="Name collision",
            why="Two skills share the same name",
            fix="Rename one skill directory",
        )
        assert err.what == "Name collision"
        assert err.why == "Two skills share the same name"
        assert err.fix == "Rename one skill directory"


class TestLogSkillError:
    def test_emits_log(self, caplog):
        test_logger = logging.getLogger("test_skill")
        with caplog.at_level(logging.ERROR, logger="test_skill"):
            log_skill_error(
                test_logger,
                "error",
                SkillErrorCode.SKILL_PARSE_ERROR,
                what="Invalid SKILL.md at '/path'",
                why="Empty file",
                fix="Add content",
            )
        assert "SKILL_PARSE_ERROR" in caplog.text

    def test_warning_level(self, caplog):
        test_logger = logging.getLogger("test_skill_warn")
        with caplog.at_level(logging.WARNING, logger="test_skill_warn"):
            log_skill_error(
                test_logger,
                "warning",
                SkillErrorCode.SKILL_YAML_FIXUP,
                what="Auto-fixed YAML",
                why="Unquoted colons",
                fix="Quote values",
            )
        assert "SKILL_YAML_FIXUP" in caplog.text

    def test_message_contains_all_parts(self, caplog):
        test_logger = logging.getLogger("test_skill_parts")
        with caplog.at_level(logging.ERROR, logger="test_skill_parts"):
            log_skill_error(
                test_logger,
                "error",
                SkillErrorCode.SKILL_NOT_FOUND,
                what="Skill not found",
                why="Not discovered",
                fix="Check paths",
            )
        assert "Skill not found" in caplog.text
        assert "Not discovered" in caplog.text
        assert "Check paths" in caplog.text


class TestSkillErrorInParser:
    def test_missing_description_returns_none(self, tmp_path):
        from framework.skills.parser import parse_skill_md

        skill_dir = tmp_path / "no-desc"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nname: no-desc\n---\nBody.\n", encoding="utf-8")
        result = parse_skill_md(skill_dir / "SKILL.md")
        assert result is None

    def test_empty_file_returns_none(self, tmp_path):
        from framework.skills.parser import parse_skill_md

        skill_dir = tmp_path / "empty"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("", encoding="utf-8")
        result = parse_skill_md(skill_dir / "SKILL.md")
        assert result is None

    def test_nonexistent_returns_none(self, tmp_path):
        from framework.skills.parser import parse_skill_md

        result = parse_skill_md(tmp_path / "ghost" / "SKILL.md")
        assert result is None

    def test_yaml_fixup_still_parses(self, tmp_path):
        from framework.skills.parser import parse_skill_md

        skill_dir = tmp_path / "colon-test"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: colon-test\ndescription: Use for: research\n---\nBody.\n",
            encoding="utf-8",
        )
        result = parse_skill_md(skill_dir / "SKILL.md")
        assert result is not None
        assert "research" in result.description
