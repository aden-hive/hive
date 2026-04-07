"""Integration tests for hive skill CLI command handlers.

Uses argparse.Namespace objects directly (not argv parsing) for concise tests.
"""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from framework.skills.cli import (
    cmd_skill_doctor,
    cmd_skill_info,
    cmd_skill_init,
    cmd_skill_install,
    cmd_skill_list,
    cmd_skill_remove,
    cmd_skill_search,
    cmd_skill_test,
    cmd_skill_validate,
)


def _make_valid_skill(parent: Path, name: str) -> Path:
    """Create a minimal valid skill in parent/name/SKILL.md."""
    d = parent / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: A test skill.\nlicense: MIT\n---\n\n## Body\n",
        encoding="utf-8",
    )
    return d


class TestCmdSkillInit:
    def test_creates_skill_md(self, tmp_path):
        args = Namespace(skill_name="test-skill", target_dir=str(tmp_path))
        result = cmd_skill_init(args)
        assert result == 0
        assert (tmp_path / "test-skill" / "SKILL.md").exists()

    def test_skill_md_contains_name(self, tmp_path):
        args = Namespace(skill_name="my-skill", target_dir=str(tmp_path))
        cmd_skill_init(args)
        content = (tmp_path / "my-skill" / "SKILL.md").read_text()
        assert "name: my-skill" in content

    def test_error_when_dir_exists(self, tmp_path, capsys):
        (tmp_path / "existing").mkdir()
        args = Namespace(skill_name="existing", target_dir=str(tmp_path))
        result = cmd_skill_init(args)
        assert result == 1
        assert "already exists" in capsys.readouterr().err

    def test_error_when_no_name(self, tmp_path, monkeypatch, capsys):
        # Non-interactive (stdin not a tty in test env) → error
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        args = Namespace(skill_name=None, target_dir=str(tmp_path))
        result = cmd_skill_init(args)
        assert result == 1


class TestCmdSkillValidate:
    def test_exits_0_on_valid_skill(self, tmp_path):
        skill_dir = _make_valid_skill(tmp_path, "my-skill")
        args = Namespace(path=str(skill_dir / "SKILL.md"))
        result = cmd_skill_validate(args)
        assert result == 0

    def test_accepts_directory_path(self, tmp_path):
        skill_dir = _make_valid_skill(tmp_path, "my-skill")
        args = Namespace(path=str(skill_dir))
        result = cmd_skill_validate(args)
        assert result == 0

    def test_exits_1_on_invalid_skill(self, tmp_path, capsys):
        skill_dir = tmp_path / "bad-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("no frontmatter here", encoding="utf-8")
        args = Namespace(path=str(skill_dir / "SKILL.md"))
        result = cmd_skill_validate(args)
        assert result == 1
        assert "[ERROR]" in capsys.readouterr().out

    def test_shows_warnings_on_valid_skill_without_license(self, tmp_path, capsys):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: No license.\n---\n\n## Body\n",
            encoding="utf-8",
        )
        args = Namespace(path=str(skill_dir / "SKILL.md"))
        result = cmd_skill_validate(args)
        assert result == 0
        assert "[WARN]" in capsys.readouterr().out


class TestCmdSkillDoctor:
    def test_defaults_pass_against_real_framework_skills(self):
        """All 6 framework default skills should be healthy (no mocking)."""
        args = Namespace(defaults=True, name=None, project_dir=None)
        result = cmd_skill_doctor(args)
        assert result == 0

    def test_named_skill_not_found_exits_1(self, tmp_path, capsys):
        args = Namespace(name="nonexistent-skill", defaults=False, project_dir=str(tmp_path))
        result = cmd_skill_doctor(args)
        assert result == 1
        assert "not found" in capsys.readouterr().err

    def test_healthy_skill_exits_0(self, tmp_path):
        _make_valid_skill(tmp_path, "my-skill")
        args = Namespace(name=None, defaults=False, project_dir=str(tmp_path))
        with patch("framework.skills.discovery.SkillDiscovery.discover") as mock_discover:
            from framework.skills.parser import ParsedSkill

            mock_discover.return_value = [
                ParsedSkill(
                    name="my-skill",
                    description="Test.",
                    location=str(tmp_path / "my-skill" / "SKILL.md"),
                    base_dir=str(tmp_path / "my-skill"),
                    source_scope="user",
                    body="## Body",
                )
            ]
            result = cmd_skill_doctor(args)
        assert result == 0


class TestCmdSkillInstall:
    def test_shows_security_notice_on_first_use(self, tmp_path, monkeypatch, capsys):
        sentinel = tmp_path / ".install_notice_shown"
        monkeypatch.setattr("framework.skills.installer.INSTALL_NOTICE_SENTINEL", sentinel)

        installed_path = tmp_path / "skills" / "my-skill"
        installed_path.mkdir(parents=True)

        args = Namespace(
            name_or_url=None,
            from_url="https://example.com/skill.git",
            pack=None,
            install_name="my-skill",
            version=None,
        )

        with patch("framework.skills.installer.install_from_git", return_value=installed_path):
            with patch("shutil.which", return_value="/usr/bin/git"):
                result = cmd_skill_install(args)

        captured = capsys.readouterr()
        assert "Security Notice" in captured.out
        assert result == 0

    def test_install_from_url_calls_install_from_git(self, tmp_path, monkeypatch):
        sentinel = tmp_path / ".install_notice_shown"
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.touch()
        monkeypatch.setattr("framework.skills.installer.INSTALL_NOTICE_SENTINEL", sentinel)

        installed_path = tmp_path / "skills" / "my-skill"
        installed_path.mkdir(parents=True)

        args = Namespace(
            name_or_url=None,
            from_url="https://github.com/org/my-skill.git",
            pack=None,
            install_name=None,
            version=None,
        )

        with patch(
            "framework.skills.installer.install_from_git", return_value=installed_path
        ) as mock_install:
            result = cmd_skill_install(args)

        mock_install.assert_called_once()
        assert result == 0

    def test_registry_not_found_exits_1(self, tmp_path, monkeypatch, capsys):
        sentinel = tmp_path / ".install_notice_shown"
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.touch()
        monkeypatch.setattr("framework.skills.installer.INSTALL_NOTICE_SENTINEL", sentinel)

        args = Namespace(
            name_or_url="nonexistent-skill",
            from_url=None,
            pack=None,
            install_name=None,
            version=None,
        )

        with patch("framework.skills.registry.RegistryClient.get_skill_entry", return_value=None):
            result = cmd_skill_install(args)

        assert result == 1
        assert "not found in registry" in capsys.readouterr().err

    def test_no_args_exits_1(self, tmp_path, monkeypatch, capsys):
        sentinel = tmp_path / ".install_notice_shown"
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.touch()
        monkeypatch.setattr("framework.skills.installer.INSTALL_NOTICE_SENTINEL", sentinel)

        args = Namespace(
            name_or_url=None, from_url=None, pack=None, install_name=None, version=None
        )
        result = cmd_skill_install(args)
        assert result == 1


class TestCmdSkillRemove:
    def test_removes_installed_skill(self, tmp_path, capsys):
        skills_dir = tmp_path / "skills"
        skill_dir = skills_dir / "my-skill"
        skill_dir.mkdir(parents=True)

        with patch("framework.skills.installer.USER_SKILLS_DIR", skills_dir):
            with patch("framework.skills.installer.remove_skill", return_value=True):
                args = Namespace(name="my-skill")
                result = cmd_skill_remove(args)

        assert result == 0
        assert "Removed" in capsys.readouterr().out

    def test_exits_1_when_not_found(self, tmp_path, capsys):
        with patch("framework.skills.installer.remove_skill", return_value=False):
            args = Namespace(name="missing-skill")
            result = cmd_skill_remove(args)

        assert result == 1
        assert "not found" in capsys.readouterr().err


class TestCmdSkillSearch:
    def test_exits_1_when_registry_unavailable(self, capsys):
        with patch("framework.skills.registry.RegistryClient.fetch_index", return_value=None):
            args = Namespace(query="research")
            result = cmd_skill_search(args)

        assert result == 1
        assert "registry unavailable" in capsys.readouterr().err.lower()

    def test_prints_results_when_found(self, capsys):
        mock_index = {
            "skills": [
                {
                    "name": "deep-research",
                    "description": "Multi-step research.",
                    "tags": ["research"],
                    "trust_tier": "official",
                }
            ]
        }
        with patch("framework.skills.registry.RegistryClient.fetch_index", return_value=mock_index):
            args = Namespace(query="research")
            result = cmd_skill_search(args)

        out = capsys.readouterr().out
        assert result == 0
        assert "deep-research" in out

    def test_no_results_message(self, capsys):
        mock_index = {"skills": []}
        with patch("framework.skills.registry.RegistryClient.fetch_index", return_value=mock_index):
            args = Namespace(query="xyzzy-nothing")
            result = cmd_skill_search(args)

        assert result == 0
        assert "No skills found" in capsys.readouterr().out


class TestCmdSkillInfo:
    def test_shows_locally_installed_skill(self, tmp_path, capsys):
        skill_dir = _make_valid_skill(tmp_path, "my-skill")
        from framework.skills.parser import ParsedSkill

        mock_skill = ParsedSkill(
            name="my-skill",
            description="A test skill.",
            location=str(skill_dir / "SKILL.md"),
            base_dir=str(skill_dir),
            source_scope="user",
            body="## Body",
            license="MIT",
        )

        with patch("framework.skills.discovery.SkillDiscovery.discover", return_value=[mock_skill]):
            args = Namespace(name="my-skill", project_dir=str(tmp_path))
            result = cmd_skill_info(args)

        out = capsys.readouterr().out
        assert result == 0
        assert "my-skill" in out
        assert "A test skill." in out

    def test_falls_back_to_registry_when_not_installed(self, capsys):
        registry_entry = {
            "name": "deep-research",
            "description": "Multi-step research.",
            "version": "1.0.0",
            "author": "anthropics",
            "trust_tier": "official",
        }

        with patch("framework.skills.discovery.SkillDiscovery.discover", return_value=[]):
            with patch(
                "framework.skills.registry.RegistryClient.get_skill_entry",
                return_value=registry_entry,
            ):
                args = Namespace(name="deep-research", project_dir=None)
                result = cmd_skill_info(args)

        out = capsys.readouterr().out
        assert result == 0
        assert "not installed" in out
        assert "deep-research" in out

    def test_exits_1_when_not_found_anywhere(self, tmp_path, capsys):
        with patch("framework.skills.discovery.SkillDiscovery.discover", return_value=[]):
            with patch(
                "framework.skills.registry.RegistryClient.get_skill_entry", return_value=None
            ):
                args = Namespace(name="ghost-skill", project_dir=str(tmp_path))
                result = cmd_skill_info(args)

        assert result == 1


class TestJsonFlag:
    def test_list_json_produces_valid_json(self, tmp_path, capsys):
        args = Namespace(project_dir=str(tmp_path), json=True)
        with patch("framework.skills.discovery.SkillDiscovery.discover", return_value=[]):
            result = cmd_skill_list(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert result == 0
        assert "skills" in data
        assert isinstance(data["skills"], list)

    def test_validate_json_valid_skill(self, tmp_path, capsys):
        from framework.skills.cli import cmd_skill_validate

        skill_dir = _make_valid_skill(tmp_path, "my-skill")
        args = Namespace(path=str(skill_dir / "SKILL.md"), json=True)
        result = cmd_skill_validate(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert result == 0
        assert data["passed"] is True
        assert data["errors"] == []
        assert "warnings" in data

    def test_doctor_defaults_json(self, capsys):
        args = Namespace(defaults=True, name=None, project_dir=None, json=True)
        result = cmd_skill_doctor(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert result == 0
        assert "skills" in data
        assert len(data["skills"]) == 6  # 6 framework default skills
        assert data["total_errors"] == 0

    def test_search_json_registry_unavailable_exits_1(self, capsys):
        with patch("framework.skills.registry.RegistryClient.fetch_index", return_value=None):
            args = Namespace(query="research", json=True)
            result = cmd_skill_search(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert result == 1
        assert "error" in data

    def test_remove_json_not_found_exits_1(self, capsys):
        with patch("framework.skills.installer.remove_skill", return_value=False):
            args = Namespace(name="ghost-skill", json=True)
            result = cmd_skill_remove(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert result == 1
        assert "error" in data


class TestCmdSkillTest:
    """Tests for hive skill test (CLI-9)."""

    def test_structural_only_valid_exits_0(self, tmp_path):
        skill_dir = _make_valid_skill(tmp_path, "my-skill")
        args = Namespace(path=str(skill_dir), input_json=None, model=None, json=False)
        result = cmd_skill_test(args)
        assert result == 0

    def test_structural_invalid_exits_1(self, tmp_path, capsys):
        skill_dir = tmp_path / "bad-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("no frontmatter", encoding="utf-8")
        args = Namespace(path=str(skill_dir), input_json=None, model=None, json=False)
        result = cmd_skill_test(args)
        assert result == 1
        assert "[ERROR]" in capsys.readouterr().out

    def test_invocation_mode_calls_provider_with_skill_body(self, tmp_path):
        skill_dir = _make_valid_skill(tmp_path, "my-skill")
        from unittest.mock import MagicMock

        from framework.llm.provider import LLMResponse

        mock_response = LLMResponse(content="Hello!", model="claude-haiku-4-5-20251001")
        mock_provider = MagicMock()
        mock_provider.complete.return_value = mock_response

        args = Namespace(
            path=str(skill_dir), input_json='{"prompt": "say hello"}', model=None, json=False
        )
        with patch("framework.llm.anthropic.AnthropicProvider", return_value=mock_provider):
            result = cmd_skill_test(args)

        assert result == 0
        call_kwargs = mock_provider.complete.call_args
        assert call_kwargs is not None
        # system should be the skill body
        assert "system" in call_kwargs.kwargs or len(call_kwargs.args) >= 2

    def test_invocation_extracts_prompt_from_json(self, tmp_path):
        skill_dir = _make_valid_skill(tmp_path, "my-skill")
        from unittest.mock import MagicMock

        from framework.llm.provider import LLMResponse

        mock_provider = MagicMock()
        mock_provider.complete.return_value = LLMResponse(
            content="response", model="claude-haiku-4-5-20251001"
        )

        args = Namespace(
            path=str(skill_dir), input_json='{"prompt": "extracted prompt"}', model=None, json=False
        )
        with patch("framework.llm.anthropic.AnthropicProvider", return_value=mock_provider):
            cmd_skill_test(args)

        call = mock_provider.complete.call_args
        messages = call.kwargs.get("messages") or (call.args[0] if call.args else [])
        assert any("extracted prompt" in m.get("content", "") for m in messages)

    def test_eval_suite_all_pass_exits_0(self, tmp_path):
        skill_dir = _make_valid_skill(tmp_path, "my-skill")
        evals_dir = skill_dir / "evals"
        evals_dir.mkdir()
        (evals_dir / "evals.json").write_text(
            json.dumps(
                {
                    "skill_name": "my-skill",
                    "evals": [
                        {"id": 1, "prompt": "Say hi.", "assertions": ["Response is a greeting"]}
                    ],
                }
            ),
            encoding="utf-8",
        )

        from unittest.mock import MagicMock

        from framework.llm.provider import LLMResponse

        mock_provider = MagicMock()
        mock_provider.complete.return_value = LLMResponse(
            content="Hello!", model="claude-haiku-4-5-20251001"
        )
        mock_judge = MagicMock()
        mock_judge.evaluate.return_value = {"passes": True, "explanation": "Looks good."}

        args = Namespace(path=str(skill_dir), input_json=None, model=None, json=False)
        with patch("framework.llm.anthropic.AnthropicProvider", return_value=mock_provider):
            with patch("framework.testing.llm_judge.LLMJudge", return_value=mock_judge):
                result = cmd_skill_test(args)

        assert result == 0

    def test_eval_any_fail_exits_1(self, tmp_path):
        skill_dir = _make_valid_skill(tmp_path, "my-skill")
        evals_dir = skill_dir / "evals"
        evals_dir.mkdir()
        (evals_dir / "evals.json").write_text(
            json.dumps(
                {
                    "skill_name": "my-skill",
                    "evals": [
                        {"id": 1, "prompt": "Say hi.", "assertions": ["Impossible assertion"]}
                    ],
                }
            ),
            encoding="utf-8",
        )

        from unittest.mock import MagicMock

        from framework.llm.provider import LLMResponse

        mock_provider = MagicMock()
        mock_provider.complete.return_value = LLMResponse(
            content="Hello!", model="claude-haiku-4-5-20251001"
        )
        mock_judge = MagicMock()
        mock_judge.evaluate.return_value = {"passes": False, "explanation": "Did not satisfy."}

        args = Namespace(path=str(skill_dir), input_json=None, model=None, json=False)
        with patch("framework.llm.anthropic.AnthropicProvider", return_value=mock_provider):
            with patch("framework.testing.llm_judge.LLMJudge", return_value=mock_judge):
                result = cmd_skill_test(args)

        assert result == 1

    def test_json_flag_structural_output(self, tmp_path, capsys):
        skill_dir = _make_valid_skill(tmp_path, "my-skill")
        args = Namespace(path=str(skill_dir), input_json=None, model=None, json=True)
        result = cmd_skill_test(args)
        out = capsys.readouterr().out
        data = json.loads(out)
        assert result == 0
        assert "structural" in data
        assert data["structural"]["passed"] is True
        assert data["skill"] == "my-skill"

    def test_json_flag_eval_results(self, tmp_path, capsys):
        skill_dir = _make_valid_skill(tmp_path, "my-skill")
        evals_dir = skill_dir / "evals"
        evals_dir.mkdir()
        (evals_dir / "evals.json").write_text(
            json.dumps(
                {
                    "skill_name": "my-skill",
                    "evals": [{"id": 1, "prompt": "Hi.", "assertions": ["Is a greeting"]}],
                }
            ),
            encoding="utf-8",
        )

        from unittest.mock import MagicMock

        from framework.llm.provider import LLMResponse

        mock_provider = MagicMock()
        mock_provider.complete.return_value = LLMResponse(
            content="Hello!", model="claude-haiku-4-5-20251001"
        )
        mock_judge = MagicMock()
        mock_judge.evaluate.return_value = {"passes": True, "explanation": "Yes."}

        args = Namespace(path=str(skill_dir), input_json=None, model=None, json=True)
        with patch("framework.llm.anthropic.AnthropicProvider", return_value=mock_provider):
            with patch("framework.testing.llm_judge.LLMJudge", return_value=mock_judge):
                result = cmd_skill_test(args)

        out = capsys.readouterr().out
        data = json.loads(out)
        assert result == 0
        assert "evals" in data
        assert data["total_passed"] == 1
        assert data["total_failed"] == 0

    def test_no_api_key_with_evals_degrades_gracefully(self, tmp_path, capsys):
        """No API key + evals present → structural checks pass, skip LLM, exit 0."""
        skill_dir = _make_valid_skill(tmp_path, "my-skill")
        (skill_dir / "evals").mkdir()
        (skill_dir / "evals" / "evals.json").write_text(
            json.dumps({"skill_name": "my-skill", "evals": []}), encoding="utf-8"
        )

        args = Namespace(path=str(skill_dir), input_json=None, model=None, json=False)
        with patch(
            "framework.llm.anthropic.AnthropicProvider",
            side_effect=ValueError("ANTHROPIC_API_KEY not set"),
        ):
            result = cmd_skill_test(args)

        assert result == 0
        assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
