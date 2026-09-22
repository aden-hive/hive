"""Compatibility tests: Anthropic skills in Hive, and Hive skills against the spec."""

import shutil
from pathlib import Path

import pytest

from framework.skills.catalog import SkillCatalog
from framework.skills.discovery import DiscoveryConfig, SkillDiscovery
from framework.skills.parser import parse_skill_md

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "anthropic_skills"

ANTHROPIC_SKILLS = [
    "claude-api",
    "pdf",
    "xlsx",
    "slack-gif-creator",
    "mcp-builder",
    "frontend-design",
]

# Expected substrings in each skill's description
EXPECTED_DESCRIPTION_SUBSTRINGS = {
    "claude-api": "Claude API",
    "pdf": "PDF",
    "xlsx": "spreadsheet",
    "slack-gif-creator": "GIF",
    "mcp-builder": "MCP",
    "frontend-design": "frontend",
}


# =============================================================================
# Section A: Anthropic Skills → Hive
# =============================================================================


@pytest.mark.parametrize("skill_name", ANTHROPIC_SKILLS)
def test_parse_without_errors(skill_name):
    path = FIXTURES_DIR / skill_name / "SKILL.md"
    result = parse_skill_md(path)
    assert result is not None, f"parse_skill_md returned None for {skill_name}"


@pytest.mark.parametrize("skill_name", ANTHROPIC_SKILLS)
def test_name_extracted_correctly(skill_name):
    path = FIXTURES_DIR / skill_name / "SKILL.md"
    result = parse_skill_md(path)
    assert result is not None
    assert result.name == skill_name


@pytest.mark.parametrize("skill_name", ANTHROPIC_SKILLS)
def test_description_extracted_correctly(skill_name):
    path = FIXTURES_DIR / skill_name / "SKILL.md"
    result = parse_skill_md(path)
    assert result is not None
    assert result.description, "description should not be empty"
    expected = EXPECTED_DESCRIPTION_SUBSTRINGS[skill_name]
    assert expected in result.description, (
        f"Expected '{expected}' in description: {result.description[:80]}..."
    )


@pytest.mark.parametrize("skill_name", ANTHROPIC_SKILLS)
def test_body_is_nonempty(skill_name):
    path = FIXTURES_DIR / skill_name / "SKILL.md"
    result = parse_skill_md(path)
    assert result is not None
    assert result.body, "body should not be empty"
    assert "#" in result.body, "body should contain at least one markdown heading"


@pytest.mark.parametrize("skill_name", ANTHROPIC_SKILLS)
def test_optional_fields_handled(skill_name):
    path = FIXTURES_DIR / skill_name / "SKILL.md"
    result = parse_skill_md(path)
    assert result is not None
    # All 6 fixtures have a license field
    assert result.license is not None, f"{skill_name} should have a license field"


@pytest.mark.parametrize("skill_name", ANTHROPIC_SKILLS)
def test_discovery_finds_skill(skill_name, tmp_path):
    # Set up directory structure that discovery expects
    skills_dir = tmp_path / ".agents" / "skills" / skill_name
    skills_dir.mkdir(parents=True)
    shutil.copy(FIXTURES_DIR / skill_name / "SKILL.md", skills_dir / "SKILL.md")

    config = DiscoveryConfig(project_root=tmp_path, skip_user_scope=True, skip_framework_scope=True)
    discovery = SkillDiscovery(config)
    results = discovery.discover()

    found_names = [s.name for s in results]
    assert skill_name in found_names, f"{skill_name} not found by discovery"


@pytest.mark.parametrize("skill_name", ANTHROPIC_SKILLS)
def test_catalog_xml_output(skill_name):
    path = FIXTURES_DIR / skill_name / "SKILL.md"
    # Must use "project" scope — catalog.to_prompt() filters out "framework" scope
    result = parse_skill_md(path, source_scope="project")
    assert result is not None

    catalog = SkillCatalog(skills=[result])
    prompt = catalog.to_prompt()

    assert f"<name>{skill_name}</name>" in prompt
    assert "<description>" in prompt


@pytest.mark.parametrize("skill_name", ANTHROPIC_SKILLS)
def test_pre_activation_loads_body(skill_name):
    path = FIXTURES_DIR / skill_name / "SKILL.md"
    result = parse_skill_md(path, source_scope="project")
    assert result is not None

    catalog = SkillCatalog(skills=[result])
    prompt = catalog.build_pre_activated_prompt([skill_name])

    assert f"Pre-Activated Skill: {skill_name}" in prompt
    assert result.body[:50] in prompt, "body content should appear in pre-activated prompt"


# =============================================================================
# Section B: Hive Default Skills → Spec
# =============================================================================

_DEFAULT_SKILLS_DIR = Path(__file__).parent.parent / "framework" / "skills" / "_default_skills"

# From defaults.py SKILL_REGISTRY
DEFAULT_SKILLS = {
    "hive.note-taking": "note-taking",
    "hive.batch-ledger": "batch-ledger",
    "hive.context-preservation": "context-preservation",
    "hive.quality-monitor": "quality-monitor",
    "hive.error-recovery": "error-recovery",
    "hive.task-decomposition": "task-decomposition",
}


@pytest.mark.parametrize("skill_name,dir_name", DEFAULT_SKILLS.items())
def test_default_skills_parse(skill_name, dir_name):
    path = _DEFAULT_SKILLS_DIR / dir_name / "SKILL.md"
    result = parse_skill_md(path, source_scope="framework")
    assert result is not None, f"Failed to parse default skill {skill_name}"


@pytest.mark.parametrize("skill_name,dir_name", DEFAULT_SKILLS.items())
def test_default_skills_have_required_fields(skill_name, dir_name):
    path = _DEFAULT_SKILLS_DIR / dir_name / "SKILL.md"
    result = parse_skill_md(path, source_scope="framework")
    assert result is not None
    assert result.name, "name should not be empty"
    assert result.description, "description should not be empty"
    assert result.body, "body should not be empty"


@pytest.mark.parametrize("skill_name,dir_name", DEFAULT_SKILLS.items())
def test_default_skills_name_convention(skill_name, dir_name):
    path = _DEFAULT_SKILLS_DIR / dir_name / "SKILL.md"
    result = parse_skill_md(path, source_scope="framework")
    assert result is not None
    assert result.name.startswith("hive."), (
        f"Default skill name should start with 'hive.': {result.name}"
    )


@pytest.mark.parametrize("skill_name,dir_name", DEFAULT_SKILLS.items())
def test_default_skills_metadata(skill_name, dir_name):
    path = _DEFAULT_SKILLS_DIR / dir_name / "SKILL.md"
    result = parse_skill_md(path, source_scope="framework")
    assert result is not None
    assert result.metadata is not None, f"{skill_name} should have metadata"
    assert "author" in result.metadata, f"{skill_name} metadata missing 'author'"
    assert "type" in result.metadata, f"{skill_name} metadata missing 'type'"
