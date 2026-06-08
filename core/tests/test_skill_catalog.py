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
        """Framework-scope skills now appear in the catalog like any other scope.

        The old design filtered framework skills out and surfaced them via
        DefaultSkillManager only. The current design folds them into the
        normal progressive-disclosure catalog.
        """
        catalog = SkillCatalog([_make_skill(source_scope="framework")])
        prompt = catalog.to_prompt()
        assert "<available_skills>" in prompt
        assert "<name>my-skill</name>" in prompt

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
        # <base_dir> is intentionally not emitted — the mandatory header
        # tells the model to resolve relative paths against the parent of
        # SKILL.md, so the redundant element was dropped.
        assert "<base_dir>" not in prompt

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

    def test_to_prompt_includes_all_scopes(self):
        """Mixed scopes: project, user, AND framework skills all appear in the catalog."""
        skills = [
            _make_skill("proj", "Project skill", "project"),
            _make_skill("usr", "User skill", "user"),
            _make_skill("fw", "Framework skill", "framework"),
        ]
        catalog = SkillCatalog(skills)
        prompt = catalog.to_prompt()

        assert "<name>proj</name>" in prompt
        assert "<name>usr</name>" in prompt
        assert "<name>fw</name>" in prompt

    def test_to_prompt_contains_mandatory_header(self):
        """The rendered catalog must carry the mandatory pre-reply checklist
        so soft guidance turns into a required step."""
        catalog = SkillCatalog([_make_skill(source_scope="project")])
        prompt = catalog.to_prompt()

        assert "## Skills (mandatory)" in prompt
        assert "Before replying: scan <available_skills>" in prompt
        assert "never read more than one skill up front" in prompt
        assert "`read_file`" in prompt
        assert "SKILL.md" in prompt

    def test_to_prompt_compact_fallback_drops_descriptions(self):
        """When the full XML body exceeds the char threshold, the compact
        variant drops <description> but keeps every skill's <name>."""
        # Each skill contributes ~100+ chars with a long description.
        # 60 skills easily pushes the body past the threshold.
        skills = [
            _make_skill(
                name=f"skill-{i:03d}",
                description="A reasonably long description " * 4,
                location=f"/s/skill-{i:03d}/SKILL.md",
                base_dir=f"/s/skill-{i:03d}",
            )
            for i in range(60)
        ]
        catalog = SkillCatalog(skills)
        prompt = catalog.to_prompt()

        # Mandatory header still present but uses the compact variant wording.
        assert "## Skills (mandatory)" in prompt
        assert "scan <available_skills> <name>" in prompt
        # Every skill's name survives …
        for i in range(60):
            assert f"<name>skill-{i:03d}</name>" in prompt
        # … but no descriptions were rendered.
        assert "<description>" not in prompt

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
