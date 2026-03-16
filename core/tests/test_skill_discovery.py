"""Tests for skill discovery (AS-1, AS-2, AS-3, AS-12, AS-15)."""

from __future__ import annotations

from pathlib import Path

import pytest

from framework.skills.discovery import (
    SkillDiscovery,
    _fix_unquoted_colon_values,
    _parse_skill_md,
    _split_frontmatter,
)
from framework.skills.models import SkillScope, TrustStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_skill(base: Path, name: str, description: str, extra: str = "") -> Path:
    """Create a minimal valid skill directory under base/name/SKILL.md."""
    skill_dir = base / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        f"---\nname: {name}\ndescription: {description}\n{extra}---\n\nSkill body.\n",
        encoding="utf-8",
    )
    return skill_md


# ---------------------------------------------------------------------------
# _split_frontmatter
# ---------------------------------------------------------------------------


class TestSplitFrontmatter:
    def test_valid_frontmatter(self):
        text = "---\nname: foo\n---\n\nBody here."
        fm, body = _split_frontmatter(text)
        assert fm == "name: foo\n"
        assert "Body here." in body

    def test_no_frontmatter(self):
        text = "Just a body."
        fm, body = _split_frontmatter(text)
        assert fm is None
        assert body == text

    def test_missing_closing_delimiter(self):
        text = "---\nname: foo\n"
        fm, body = _split_frontmatter(text)
        assert fm is None

    def test_body_stripped_of_leading_newline(self):
        text = "---\nname: x\n---\n\nHello"
        _, body = _split_frontmatter(text)
        assert body.startswith("Hello")


# ---------------------------------------------------------------------------
# _fix_unquoted_colon_values (AS-15)
# ---------------------------------------------------------------------------


class TestFixUnquotedColonValues:
    def test_fixes_colon_in_description(self):
        text = "description: Multi-step research: finds sources"
        fixed = _fix_unquoted_colon_values(text)
        assert 'description: "Multi-step research: finds sources"' in fixed

    def test_leaves_already_quoted_values_alone(self):
        text = 'description: "Already: quoted"'
        fixed = _fix_unquoted_colon_values(text)
        assert fixed == text

    def test_leaves_list_values_alone(self):
        text = "compatibility: [claude-code, cursor]"
        fixed = _fix_unquoted_colon_values(text)
        assert fixed == text

    def test_no_colon_in_value_unchanged(self):
        text = "name: my-skill"
        fixed = _fix_unquoted_colon_values(text)
        assert fixed == text


# ---------------------------------------------------------------------------
# _parse_skill_md
# ---------------------------------------------------------------------------


class TestParseSkillMd:
    def test_valid_minimal(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        md = skill_dir / "SKILL.md"
        md.write_text("---\nname: my-skill\ndescription: Does something\n---\n", encoding="utf-8")
        entry = _parse_skill_md(md, SkillScope.USER)
        assert entry is not None
        assert entry.name == "my-skill"
        assert entry.description == "Does something"
        assert entry.trust_status == TrustStatus.TRUSTED

    def test_project_scope_marked_pending(self, tmp_path):
        skill_dir = tmp_path / "proj-skill"
        skill_dir.mkdir()
        md = skill_dir / "SKILL.md"
        md.write_text("---\nname: proj-skill\ndescription: x\n---\n", encoding="utf-8")
        entry = _parse_skill_md(md, SkillScope.PROJECT)
        assert entry is not None
        assert entry.trust_status == TrustStatus.PENDING_CONSENT

    def test_missing_description_returns_none(self, tmp_path):
        skill_dir = tmp_path / "no-desc"
        skill_dir.mkdir()
        md = skill_dir / "SKILL.md"
        md.write_text("---\nname: no-desc\n---\n", encoding="utf-8")
        assert _parse_skill_md(md, SkillScope.USER) is None

    def test_empty_description_returns_none(self, tmp_path):
        skill_dir = tmp_path / "empty-desc"
        skill_dir.mkdir()
        md = skill_dir / "SKILL.md"
        md.write_text("---\nname: empty-desc\ndescription: \n---\n", encoding="utf-8")
        assert _parse_skill_md(md, SkillScope.USER) is None

    def test_optional_fields_parsed(self, tmp_path):
        skill_dir = tmp_path / "full-skill"
        skill_dir.mkdir()
        md = skill_dir / "SKILL.md"
        md.write_text(
            "---\n"
            "name: full-skill\n"
            "description: Full featured\n"
            "license: MIT\n"
            "compatibility:\n  - claude-code\n"
            "allowed-tools:\n  - web_search\n"
            "---\n",
            encoding="utf-8",
        )
        entry = _parse_skill_md(md, SkillScope.USER)
        assert entry is not None
        assert entry.license == "MIT"
        assert "claude-code" in entry.compatibility
        assert "web_search" in entry.allowed_tools

    def test_colon_fixup_loads_successfully(self, tmp_path):
        skill_dir = tmp_path / "colon-skill"
        skill_dir.mkdir()
        md = skill_dir / "SKILL.md"
        # description has an unquoted colon — common cross-client issue
        md.write_text(
            "---\nname: colon-skill\ndescription: Research: finds and synthesises\n---\n",
            encoding="utf-8",
        )
        entry = _parse_skill_md(md, SkillScope.USER)
        assert entry is not None
        assert "Research" in entry.description

    def test_name_mismatch_warning_but_loads(self, tmp_path, caplog):
        skill_dir = tmp_path / "dir-name"
        skill_dir.mkdir()
        md = skill_dir / "SKILL.md"
        md.write_text("---\nname: different-name\ndescription: ok\n---\n", encoding="utf-8")
        import logging
        with caplog.at_level(logging.WARNING):
            entry = _parse_skill_md(md, SkillScope.USER)
        assert entry is not None
        assert entry.name == "different-name"

    def test_name_fallback_to_dir_when_missing(self, tmp_path):
        skill_dir = tmp_path / "fallback-dir"
        skill_dir.mkdir()
        md = skill_dir / "SKILL.md"
        md.write_text("---\ndescription: has no name\n---\n", encoding="utf-8")
        entry = _parse_skill_md(md, SkillScope.USER)
        assert entry is not None
        assert entry.name == "fallback-dir"


# ---------------------------------------------------------------------------
# SkillDiscovery
# ---------------------------------------------------------------------------


class TestSkillDiscovery:
    def test_discovers_agents_skills_dir(self, tmp_path):
        skills_root = tmp_path / ".agents" / "skills"
        write_skill(skills_root, "my-skill", "Does something")
        skills = SkillDiscovery().discover(tmp_path)
        assert any(s.name == "my-skill" for s in skills)

    def test_discovers_hive_skills_dir(self, tmp_path):
        skills_root = tmp_path / ".hive" / "skills"
        write_skill(skills_root, "hive-skill", "Hive specific")
        skills = SkillDiscovery().discover(tmp_path)
        assert any(s.name == "hive-skill" for s in skills)

    def test_project_scope_assigned_correctly(self, tmp_path):
        skills_root = tmp_path / ".agents" / "skills"
        write_skill(skills_root, "proj-skill", "Project skill")
        skills = SkillDiscovery().discover(tmp_path)
        proj = next(s for s in skills if s.name == "proj-skill")
        assert proj.source_scope == SkillScope.PROJECT
        assert proj.trust_status == TrustStatus.PENDING_CONSENT

    def test_hive_overrides_agents_within_project(self, tmp_path, caplog):
        """PRD §4.1: .hive/skills/ overrides .agents/skills/ for same name."""
        write_skill(tmp_path / ".hive" / "skills", "same-name", "Hive version")
        write_skill(tmp_path / ".agents" / "skills", "same-name", "Agents version")
        import logging
        with caplog.at_level(logging.WARNING):
            skills = SkillDiscovery().discover(tmp_path)
        matches = [s for s in skills if s.name == "same-name"]
        assert len(matches) == 1
        assert matches[0].description == "Hive version"

    def test_project_overrides_user(self, tmp_path, monkeypatch):
        """PRD §4.1: project scope overrides user scope for same name."""
        user_skills = tmp_path / "user_home" / ".hive" / "skills"
        proj_skills = tmp_path / "project" / ".hive" / "skills"
        write_skill(user_skills, "shared-skill", "User version")
        write_skill(proj_skills, "shared-skill", "Project version")

        # Monkeypatch home so user skills are found
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "user_home"))

        skills = SkillDiscovery().discover(tmp_path / "project")
        matches = [s for s in skills if s.name == "shared-skill"]
        assert len(matches) == 1
        assert matches[0].description == "Project version"

    def test_no_project_dir_skips_project_scope(self, tmp_path, monkeypatch):
        """When project_dir=None, no project-scope skills should appear."""
        # Create user skills only
        user_home = tmp_path / "home"
        write_skill(user_home / ".hive" / "skills", "user-only", "User skill")
        monkeypatch.setattr(Path, "home", staticmethod(lambda: user_home))

        skills = SkillDiscovery().discover(None)
        assert all(s.source_scope != SkillScope.PROJECT for s in skills)

    def test_skips_blocked_dirs(self, tmp_path):
        """Skills inside .git, node_modules etc. should not be discovered."""
        blocked = tmp_path / ".agents" / "skills" / ".git"
        blocked.mkdir(parents=True)
        md = blocked / "SKILL.md"
        md.write_text("---\nname: evil\ndescription: bad\n---\n", encoding="utf-8")
        skills = SkillDiscovery().discover(tmp_path)
        assert not any(s.name == "evil" for s in skills)

    def test_missing_skills_dir_returns_empty(self, tmp_path):
        """No crash when skill directories don't exist."""
        skills = SkillDiscovery().discover(tmp_path)
        # Filter to project scope — should be empty
        proj = [s for s in skills if s.source_scope == SkillScope.PROJECT]
        assert proj == []

    def test_invalid_skill_md_skipped_gracefully(self, tmp_path):
        """Completely unparseable SKILL.md should be skipped without crashing."""
        skill_dir = tmp_path / ".agents" / "skills" / "broken"
        skill_dir.mkdir(parents=True)
        md = skill_dir / "SKILL.md"
        # Write invalid YAML that even fixup can't salvage
        md.write_text("---\n{{{not: valid: yaml:::\n---\n", encoding="utf-8")
        # Should not raise
        skills = SkillDiscovery().discover(tmp_path)
        assert not any(s.name == "broken" for s in skills)

    def test_max_depth_respected(self, tmp_path):
        """Skills nested beyond max depth (4) should not be found."""
        deep = tmp_path / ".agents" / "skills" / "a" / "b" / "c" / "d" / "e"
        deep.mkdir(parents=True)
        md = deep / "SKILL.md"
        md.write_text("---\nname: deep\ndescription: too deep\n---\n", encoding="utf-8")
        skills = SkillDiscovery().discover(tmp_path)
        assert not any(s.name == "deep" for s in skills)

    def test_performance_50_skills(self, tmp_path):
        """Skill discovery should complete in under 500ms for 50 skills (NFR-1)."""
        import time

        skills_root = tmp_path / ".hive" / "skills"
        for i in range(50):
            write_skill(skills_root, f"skill-{i:02d}", f"Skill number {i}")

        start = time.perf_counter()
        skills = SkillDiscovery().discover(tmp_path)
        elapsed = time.perf_counter() - start

        assert len([s for s in skills if s.source_scope == SkillScope.PROJECT]) == 50
        assert elapsed < 0.5, f"Discovery took {elapsed:.3f}s, expected <0.5s"
