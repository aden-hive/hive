"""Tests for the skill catalog and prompt generation."""

from framework.skills.catalog import SkillCatalog
from framework.skills.parser import ParsedSkill


def _make_skill(
    name: str = "my-skill",
    description: str = "A test skill.",
    source_scope: str = "project",
    body: str = "Instructions here.",
    location: str = "/tmp/skills/my-skill/SKILL.md",
    base_dir: str = "/tmp/skills/my-skill",
) -> ParsedSkill:
    return ParsedSkill(
        name=name,
        description=description,
        location=location,
        base_dir=base_dir,
        source_scope=source_scope,
        body=body,
    )


class TestSkillCatalog:
    def test_add_and_get(self):
        catalog = SkillCatalog()
        skill = _make_skill()
        catalog.add(skill)

        assert catalog.get("my-skill") is skill
        assert catalog.get("nonexistent") is None
        assert catalog.skill_count == 1

    def test_init_with_skills_list(self):
        skills = [_make_skill("a", "Skill A"), _make_skill("b", "Skill B")]
        catalog = SkillCatalog(skills)

        assert catalog.skill_count == 2
        assert catalog.get("a") is not None
        assert catalog.get("b") is not None

    def test_activation_tracking(self):
        catalog = SkillCatalog([_make_skill()])
        assert not catalog.is_activated("my-skill")

        catalog.mark_activated("my-skill")
        assert catalog.is_activated("my-skill")

    def test_allowlisted_dirs(self):
        skills = [
            _make_skill("a", base_dir="/skills/a"),
            _make_skill("b", base_dir="/skills/b"),
        ]
        catalog = SkillCatalog(skills)
        dirs = catalog.allowlisted_dirs

        assert "/skills/a" in dirs
        assert "/skills/b" in dirs

    def test_to_prompt_empty_catalog(self):
        catalog = SkillCatalog()
        assert catalog.to_prompt() == ""

    def test_to_prompt_framework_only(self):
        """Framework-scope skills should NOT appear in the catalog prompt."""
        catalog = SkillCatalog([_make_skill(source_scope="framework")])
        assert catalog.to_prompt() == ""

    def test_to_prompt_xml_generation(self):
        skills = [
            _make_skill(
                "alpha",
                "Alpha skill",
                "project",
                location="/p/alpha/SKILL.md",
                base_dir="/p/alpha",
            ),
            _make_skill("beta", "Beta skill", "user", location="/u/beta/SKILL.md"),
        ]
        catalog = SkillCatalog(skills)
        prompt = catalog.to_prompt()

        assert "<available_skills>" in prompt
        assert "</available_skills>" in prompt
        assert "<name>alpha</name>" in prompt
        assert "<name>beta</name>" in prompt
        assert "<description>Alpha skill</description>" in prompt
        assert "<location>/p/alpha/SKILL.md</location>" in prompt
        assert "<base_dir>/p/alpha</base_dir>" in prompt

    def test_to_prompt_sorted_by_name(self):
        skills = [
            _make_skill("zebra", "Z skill", "project"),
            _make_skill("alpha", "A skill", "project"),
        ]
        catalog = SkillCatalog(skills)
        prompt = catalog.to_prompt()

        alpha_pos = prompt.index("alpha")
        zebra_pos = prompt.index("zebra")
        assert alpha_pos < zebra_pos

    def test_to_prompt_xml_escaping(self):
        skill = _make_skill("test", 'Has <special> & "chars"', "project")
        catalog = SkillCatalog([skill])
        prompt = catalog.to_prompt()

        assert "&lt;special&gt;" in prompt
        assert "&amp;" in prompt

    def test_to_prompt_excludes_framework_includes_others(self):
        """Mixed scopes: only framework skills are excluded from catalog."""
        skills = [
            _make_skill("proj", "Project skill", "project"),
            _make_skill("usr", "User skill", "user"),
            _make_skill("fw", "Framework skill", "framework"),
        ]
        catalog = SkillCatalog(skills)
        prompt = catalog.to_prompt()

        assert "<name>proj</name>" in prompt
        assert "<name>usr</name>" in prompt
        assert "fw" not in prompt

    def test_to_prompt_contains_behavioral_instruction(self):
        catalog = SkillCatalog([_make_skill(source_scope="project")])
        prompt = catalog.to_prompt()

        assert "When a task matches a skill's description" in prompt
        assert "SKILL.md" in prompt

    def test_build_pre_activated_prompt(self):
        skill = _make_skill("research", body="## Deep Research\nDo thorough research.")
        catalog = SkillCatalog([skill])
        prompt = catalog.build_pre_activated_prompt(["research"])

        assert "Pre-Activated Skill: research" in prompt
        assert "## Deep Research" in prompt
        assert catalog.is_activated("research")

    def test_build_pre_activated_skips_already_activated(self):
        skill = _make_skill("research", body="Research body")
        catalog = SkillCatalog([skill])
        catalog.mark_activated("research")

        prompt = catalog.build_pre_activated_prompt(["research"])
        assert prompt == ""

    def test_build_pre_activated_missing_skill(self):
        catalog = SkillCatalog()
        prompt = catalog.build_pre_activated_prompt(["nonexistent"])
        assert prompt == ""

    def test_build_pre_activated_multiple(self):
        skills = [
            _make_skill("a", body="Body A"),
            _make_skill("b", body="Body B"),
        ]
        catalog = SkillCatalog(skills)
        prompt = catalog.build_pre_activated_prompt(["a", "b"])

        assert "Pre-Activated Skill: a" in prompt
        assert "Body A" in prompt
        assert "Pre-Activated Skill: b" in prompt
        assert "Body B" in prompt
        assert catalog.is_activated("a")
        assert catalog.is_activated("b")

    def test_duplicate_add_overwrites(self):
        """Adding a skill with the same name replaces the previous one."""
        catalog = SkillCatalog()
        catalog.add(_make_skill("x", "First"))
        catalog.add(_make_skill("x", "Second"))

        assert catalog.skill_count == 1
        assert catalog.get("x").description == "Second"
