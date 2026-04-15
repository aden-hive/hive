"""Tests for default skills — parsing, token budget, and configuration."""

from pathlib import Path

import pytest

from framework.skills.config import DefaultSkillConfig, SkillsConfig
from framework.skills.defaults import (
    DATA_BUFFER_KEYS,
    SKILL_REGISTRY,
    DefaultSkillManager,
    is_batch_scenario,
)
from framework.skills.parser import parse_skill_md

_DEFAULT_SKILLS_DIR = (
    Path(__file__).resolve().parent.parent / "framework" / "skills" / "_default_skills"
)


class TestDefaultSkillFiles:
    """Verify all built-in SKILL.md files parse correctly."""

    def test_all_skills_exist(self):
        assert len(SKILL_REGISTRY) == 8

    @pytest.mark.parametrize("skill_name,dir_name", list(SKILL_REGISTRY.items()))
    def test_skill_parses(self, skill_name, dir_name):
        path = _DEFAULT_SKILLS_DIR / dir_name / "SKILL.md"
        assert path.is_file(), f"Missing SKILL.md at {path}"

        parsed = parse_skill_md(path, source_scope="framework")
        assert parsed is not None, f"Failed to parse {path}"
        assert parsed.name == skill_name
        assert parsed.description
        assert parsed.body
        assert parsed.source_scope == "framework"

    def test_combined_token_budget(self):
        """All default skill bodies combined should stay within the protocols budget.

        Ceiling is 5000 tokens (~20000 chars): the prompt-injection path
        appends every registered skill body to the system prompt, so
        uncontrolled growth would balloon every LLM call. 5000 gives
        headroom over today's ~3500 while still catching obvious bloat.
        """
        total_chars = 0
        for dir_name in SKILL_REGISTRY.values():
            path = _DEFAULT_SKILLS_DIR / dir_name / "SKILL.md"
            parsed = parse_skill_md(path, source_scope="framework")
            assert parsed is not None
            total_chars += len(parsed.body)

        approx_tokens = total_chars // 4
        assert approx_tokens < 5000, (
            f"Combined default skill bodies are ~{approx_tokens} tokens "
            f"({total_chars} chars), exceeding the 5000 token budget"
        )

    def test_data_buffer_keys_all_prefixed(self):
        """All data buffer keys must start with underscore."""
        for key in DATA_BUFFER_KEYS:
            assert key.startswith("_"), f"Data buffer key missing _ prefix: {key}"


class TestDefaultSkillManager:
    def test_load_all_defaults(self):
        manager = DefaultSkillManager()
        manager.load()

        assert len(manager.active_skill_names) == 8
        for name in SKILL_REGISTRY:
            assert name in manager.active_skill_names

    def test_load_idempotent(self):
        manager = DefaultSkillManager()
        manager.load()
        first_skills = dict(manager.active_skills)
        manager.load()
        assert manager.active_skills == first_skills

    def test_build_protocols_prompt(self):
        manager = DefaultSkillManager()
        manager.load()
        prompt = manager.build_protocols_prompt()

        assert prompt.startswith("## Operational Protocols")
        # Should contain content from each active skill
        for name in SKILL_REGISTRY:
            skill = manager.active_skills[name]
            # At least some of the body should appear
            assert skill.body[:20] in prompt

    def test_protocols_prompt_empty_when_all_disabled(self):
        config = SkillsConfig(all_defaults_disabled=True)
        manager = DefaultSkillManager(config)
        manager.load()

        assert manager.build_protocols_prompt() == ""
        assert manager.active_skill_names == []

    def test_disable_single_skill(self):
        config = SkillsConfig.from_agent_vars(
            default_skills={"hive.quality-monitor": {"enabled": False}}
        )
        manager = DefaultSkillManager(config)
        manager.load()

        assert "hive.quality-monitor" not in manager.active_skill_names
        assert len(manager.active_skill_names) == len(SKILL_REGISTRY) - 1

    def test_disable_all_via_convention(self):
        config = SkillsConfig.from_agent_vars(default_skills={"_all": {"enabled": False}})
        manager = DefaultSkillManager(config)
        manager.load()

        assert manager.active_skill_names == []

    def test_log_active_skills(self, caplog):
        import logging

        with caplog.at_level(logging.INFO, logger="framework.skills.defaults"):
            manager = DefaultSkillManager()
            manager.load()
            manager.log_active_skills()

        assert "Default skills active:" in caplog.text

    def test_log_all_disabled(self, caplog):
        import logging

        config = SkillsConfig(all_defaults_disabled=True)
        with caplog.at_level(logging.INFO, logger="framework.skills.defaults"):
            manager = DefaultSkillManager(config)
            manager.load()
            manager.log_active_skills()

        assert "all disabled" in caplog.text


class TestSkillsConfig:
    def test_default_is_enabled(self):
        config = SkillsConfig()
        assert config.is_default_enabled("hive.note-taking") is True

    def test_explicit_disable(self):
        config = SkillsConfig(
            default_skills={"hive.note-taking": DefaultSkillConfig(enabled=False)}
        )
        assert config.is_default_enabled("hive.note-taking") is False
        assert config.is_default_enabled("hive.batch-ledger") is True

    def test_all_disabled_flag(self):
        config = SkillsConfig(all_defaults_disabled=True)
        assert config.is_default_enabled("hive.note-taking") is False
        assert config.is_default_enabled("anything") is False

    def test_from_agent_vars_basic(self):
        config = SkillsConfig.from_agent_vars(
            default_skills={
                "hive.note-taking": {"enabled": True},
                "hive.quality-monitor": {"enabled": False},
            },
            skills=["deep-research"],
        )
        assert config.is_default_enabled("hive.note-taking") is True
        assert config.is_default_enabled("hive.quality-monitor") is False
        assert config.skills == ["deep-research"]

    def test_from_agent_vars_bool_shorthand(self):
        config = SkillsConfig.from_agent_vars(default_skills={"hive.note-taking": False})
        assert config.is_default_enabled("hive.note-taking") is False

    def test_from_agent_vars_all_disabled(self):
        config = SkillsConfig.from_agent_vars(default_skills={"_all": {"enabled": False}})
        assert config.all_defaults_disabled is True

    def test_get_default_overrides(self):
        config = SkillsConfig.from_agent_vars(
            default_skills={
                "hive.batch-ledger": {"enabled": True, "checkpoint_every_n": 10},
            }
        )
        overrides = config.get_default_overrides("hive.batch-ledger")
        assert overrides == {"checkpoint_every_n": 10}

    def test_get_default_overrides_empty(self):
        config = SkillsConfig()
        assert config.get_default_overrides("hive.note-taking") == {}

    def test_from_agent_vars_none_inputs(self):
        config = SkillsConfig.from_agent_vars(default_skills=None, skills=None)
        assert config.skills == []
        assert config.default_skills == {}
        assert config.all_defaults_disabled is False


class TestConfigOverrideSubstitution:
    """Config overrides replace {{placeholder}} values in injected protocol text."""

    def test_quality_monitor_default_interval(self):
        manager = DefaultSkillManager()
        manager.load()
        prompt = manager.build_protocols_prompt()
        assert "Every 5 iterations" in prompt

    def test_quality_monitor_override_interval(self):
        config = SkillsConfig.from_agent_vars(
            default_skills={"hive.quality-monitor": {"assessment_interval": 10}}
        )
        manager = DefaultSkillManager(config)
        manager.load()
        prompt = manager.build_protocols_prompt()
        assert "Every 10 iterations" in prompt
        assert "Every 5 iterations" not in prompt

    def test_error_recovery_default_retries(self):
        manager = DefaultSkillManager()
        manager.load()
        prompt = manager.build_protocols_prompt()
        assert "3+ times" in prompt

    def test_error_recovery_override_retries(self):
        config = SkillsConfig.from_agent_vars(
            default_skills={"hive.error-recovery": {"max_retries_per_tool": 5}}
        )
        manager = DefaultSkillManager(config)
        manager.load()
        prompt = manager.build_protocols_prompt()
        assert "5+ times" in prompt
        assert "3+ times" not in prompt

    def test_context_preservation_default_threshold(self):
        manager = DefaultSkillManager()
        manager.load()
        prompt = manager.build_protocols_prompt()
        assert "45%" in prompt

    def test_context_preservation_override_threshold(self):
        config = SkillsConfig.from_agent_vars(
            default_skills={"hive.context-preservation": {"warn_at_usage_ratio": 0.4}}
        )
        manager = DefaultSkillManager(config)
        manager.load()
        prompt = manager.build_protocols_prompt()
        assert "40%" in prompt
        assert "45%" not in prompt

    def test_no_unreplaced_placeholders_with_defaults(self):
        """All {{...}} placeholders should be replaced when using defaults."""
        manager = DefaultSkillManager()
        manager.load()
        prompt = manager.build_protocols_prompt()
        assert "{{" not in prompt


class TestBatchAutoDetection:
    """DS-12: is_batch_scenario() and batch_init_nudge property."""

    def test_detects_list_of(self):
        assert is_batch_scenario("process a list of 100 leads") is True

    def test_detects_collection_of(self):
        assert is_batch_scenario("a collection of invoices") is True

    def test_detects_items(self):
        assert is_batch_scenario("go through all items in the spreadsheet") is True

    def test_detects_for_each(self):
        assert is_batch_scenario("for each record, send an email") is True

    def test_no_match_single_task(self):
        assert is_batch_scenario("write a summary of the quarterly report") is False

    def test_batch_nudge_active_by_default(self):
        manager = DefaultSkillManager()
        manager.load()
        assert manager.batch_init_nudge is not None
        assert "_batch_ledger" in manager.batch_init_nudge

    def test_batch_nudge_none_when_skill_disabled(self):
        config = SkillsConfig.from_agent_vars(
            default_skills={"hive.batch-ledger": {"enabled": False}}
        )
        manager = DefaultSkillManager(config)
        manager.load()
        assert manager.batch_init_nudge is None

    def test_batch_nudge_none_when_auto_detect_disabled(self):
        config = SkillsConfig.from_agent_vars(
            default_skills={"hive.batch-ledger": {"auto_detect_batch": False}}
        )
        manager = DefaultSkillManager(config)
        manager.load()
        assert manager.batch_init_nudge is None


class TestContextWarnRatio:
    """DS-13: context_warn_ratio property."""

    def test_default_ratio(self):
        manager = DefaultSkillManager()
        manager.load()
        assert manager.context_warn_ratio == pytest.approx(0.45)

    def test_override_ratio(self):
        config = SkillsConfig.from_agent_vars(
            default_skills={"hive.context-preservation": {"warn_at_usage_ratio": 0.3}}
        )
        manager = DefaultSkillManager(config)
        manager.load()
        assert manager.context_warn_ratio == pytest.approx(0.3)

    def test_ratio_none_when_skill_disabled(self):
        config = SkillsConfig.from_agent_vars(
            default_skills={"hive.context-preservation": {"enabled": False}}
        )
        manager = DefaultSkillManager(config)
        manager.load()
        assert manager.context_warn_ratio is None
