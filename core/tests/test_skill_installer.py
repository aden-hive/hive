"""Tests for skill install, remove, and fork operations."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from framework.skills.installer import (
    fork_skill,
    install_from_git,
    maybe_show_install_notice,
    remove_skill,
)
from framework.skills.parser import ParsedSkill
from framework.skills.skill_errors import SkillError


def _make_skill_dir(parent: Path, name: str, body: str = "## Instructions\n\nDo things.") -> Path:
    """Create a minimal skill directory with a valid SKILL.md."""
    skill_dir = parent / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: A test skill.\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return skill_dir


def _make_parsed_skill(base_dir: Path, name: str) -> ParsedSkill:
    """Create a ParsedSkill pointing to base_dir."""
    return ParsedSkill(
        name=name,
        description="Test skill.",
        location=str(base_dir / "SKILL.md"),
        base_dir=str(base_dir),
        source_scope="user",
        body="## Instructions",
    )


class TestInstallFromGit:
    def test_copies_skill_dir_to_target(self, tmp_path):
        """Successful clone copies skill directory to target."""
        source_repo = tmp_path / "repo"
        _make_skill_dir(source_repo, ".")  # SKILL.md at repo root

        target = tmp_path / "skills"

        def fake_clone(git_url, target_path, version=None):
            # Simulate git clone by copying source_repo into target_path
            import shutil

            if target_path.exists():
                shutil.rmtree(target_path)
            shutil.copytree(source_repo, target_path)

        with patch("framework.skills.installer._git_clone_shallow", side_effect=fake_clone):
            with patch("shutil.which", return_value="/usr/bin/git"):
                dest = install_from_git(
                    git_url="https://example.com/skill.git",
                    skill_name="my-skill",
                    target_dir=target,
                )

        assert (dest / "SKILL.md").exists()
        assert dest == target / "my-skill"

    def test_raises_when_git_not_found(self, tmp_path):
        with patch("shutil.which", return_value=None):
            with pytest.raises(SkillError) as exc_info:
                install_from_git(
                    git_url="https://example.com/skill.git",
                    skill_name="my-skill",
                    target_dir=tmp_path / "skills",
                )
        assert "git is not installed" in exc_info.value.why

    def test_raises_when_skill_md_missing(self, tmp_path):
        """Clone succeeds but no SKILL.md in the subdirectory → error."""
        empty_repo = tmp_path / "empty_repo"
        empty_repo.mkdir()

        def fake_clone(git_url, target_path, version=None):
            import shutil

            if target_path.exists():
                shutil.rmtree(target_path)
            shutil.copytree(empty_repo, target_path)

        with patch("framework.skills.installer._git_clone_shallow", side_effect=fake_clone):
            with patch("shutil.which", return_value="/usr/bin/git"):
                with pytest.raises(SkillError) as exc_info:
                    install_from_git(
                        git_url="https://example.com/skill.git",
                        skill_name="my-skill",
                        subdirectory="deep-research",
                        target_dir=tmp_path / "skills",
                    )
        assert exc_info.value.code.value == "SKILL_NOT_FOUND"

    def test_raises_when_target_already_exists(self, tmp_path):
        skills_dir = tmp_path / "skills"
        (skills_dir / "existing-skill").mkdir(parents=True)

        with patch("shutil.which", return_value="/usr/bin/git"):
            with pytest.raises(SkillError) as exc_info:
                install_from_git(
                    git_url="https://example.com/skill.git",
                    skill_name="existing-skill",
                    target_dir=skills_dir,
                )
        assert "already exists" in exc_info.value.why

    def test_cleans_temp_dir_on_clone_failure(self, tmp_path):
        """Temporary directory is cleaned up even when clone fails."""
        created_tmp_dirs = []
        original_mkdtemp = __import__("tempfile").mkdtemp

        def tracking_mkdtemp(**kwargs):
            d = original_mkdtemp(**kwargs)
            created_tmp_dirs.append(d)
            return d

        def failing_clone(git_url, target_path, version=None):
            from framework.skills.skill_errors import SkillErrorCode as SEC

            raise SkillError(
                code=SEC.SKILL_ACTIVATION_FAILED,
                what="clone failed",
                why="network error",
                fix="check network",
            )

        with patch("tempfile.mkdtemp", side_effect=tracking_mkdtemp):
            with patch("framework.skills.installer._git_clone_shallow", side_effect=failing_clone):
                with patch("shutil.which", return_value="/usr/bin/git"):
                    with pytest.raises(SkillError):
                        install_from_git(
                            git_url="https://example.com/skill.git",
                            skill_name="my-skill",
                            target_dir=tmp_path / "skills",
                        )

        # All created temp dirs should be cleaned up
        for d in created_tmp_dirs:
            assert not Path(d).exists(), f"Temp dir not cleaned: {d}"


class TestRemoveSkill:
    def test_removes_existing_skill(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skill_dir = _make_skill_dir(skills_dir, "my-skill")
        assert skill_dir.exists()

        result = remove_skill("my-skill", skills_dir=skills_dir)
        assert result is True
        assert not skill_dir.exists()

    def test_returns_false_when_not_found(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        result = remove_skill("nonexistent", skills_dir=skills_dir)
        assert result is False

    def test_raises_on_permission_error(self, tmp_path):
        skills_dir = tmp_path / "skills"
        _make_skill_dir(skills_dir, "locked-skill")

        with patch("shutil.rmtree", side_effect=OSError("permission denied")):
            with pytest.raises(SkillError) as exc_info:
                remove_skill("locked-skill", skills_dir=skills_dir)
        assert "permission" in exc_info.value.why.lower()


class TestForkSkill:
    def test_copies_skill_to_new_name(self, tmp_path):
        source_dir = _make_skill_dir(tmp_path / "sources", "my-skill")
        source = _make_parsed_skill(source_dir, "my-skill")
        target_parent = tmp_path / "skills"

        dest = fork_skill(source, "my-skill-fork", target_parent)

        assert dest.exists()
        assert (dest / "SKILL.md").exists()

    def test_rewrites_name_in_skill_md(self, tmp_path):
        source_dir = _make_skill_dir(tmp_path / "sources", "original")
        source = _make_parsed_skill(source_dir, "original")
        target_parent = tmp_path / "skills"

        dest = fork_skill(source, "forked", target_parent)

        import yaml

        content = (dest / "SKILL.md").read_text(encoding="utf-8")
        parts = content.split("---", 2)
        fm = yaml.safe_load(parts[1])
        assert fm["name"] == "forked"

    def test_raises_when_dest_already_exists(self, tmp_path):
        source_dir = _make_skill_dir(tmp_path / "sources", "my-skill")
        source = _make_parsed_skill(source_dir, "my-skill")
        target_parent = tmp_path / "skills"
        (target_parent / "my-skill-fork").mkdir(parents=True)

        with pytest.raises(SkillError) as exc_info:
            fork_skill(source, "my-skill-fork", target_parent)
        assert "already exists" in exc_info.value.why

    def test_preserves_scripts_and_references(self, tmp_path):
        source_dir = _make_skill_dir(tmp_path / "sources", "my-skill")
        (source_dir / "scripts").mkdir()
        (source_dir / "scripts" / "run.sh").write_text("#!/bin/sh\necho hi")
        (source_dir / "references").mkdir()
        (source_dir / "references" / "guide.md").write_text("# Guide")
        source = _make_parsed_skill(source_dir, "my-skill")
        target_parent = tmp_path / "skills"

        dest = fork_skill(source, "fork", target_parent)

        assert (dest / "scripts" / "run.sh").exists()
        assert (dest / "references" / "guide.md").exists()


class TestInstallNotice:
    def test_shown_on_first_call(self, tmp_path, monkeypatch, capsys):
        sentinel = tmp_path / ".install_notice_shown"
        monkeypatch.setattr("framework.skills.installer.INSTALL_NOTICE_SENTINEL", sentinel)

        maybe_show_install_notice()

        captured = capsys.readouterr()
        assert "Security Notice" in captured.out
        assert sentinel.exists()

    def test_not_shown_on_second_call(self, tmp_path, monkeypatch, capsys):
        sentinel = tmp_path / ".install_notice_shown"
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.touch()
        monkeypatch.setattr("framework.skills.installer.INSTALL_NOTICE_SENTINEL", sentinel)

        maybe_show_install_notice()

        captured = capsys.readouterr()
        assert "Security Notice" not in captured.out
