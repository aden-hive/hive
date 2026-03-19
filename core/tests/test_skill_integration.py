"""Integration tests for the skill system — prompt composition and backward compatibility."""

from framework.graph.prompt_composer import compose_system_prompt
from framework.skills.catalog import SkillCatalog
from framework.skills.config import SkillsConfig
from framework.skills.defaults import DefaultSkillManager
from framework.skills.discovery import DiscoveryConfig, SkillDiscovery
from framework.skills.parser import ParsedSkill


def _make_skill(
    name: str = "test-skill",
    description: str = "A test skill.",
    source_scope: str = "project",
    body: str = "Skill instructions.",
    location: str = "/tmp/skills/test-skill/SKILL.md",
    base_dir: str = "/tmp/skills/test-skill",
) -> ParsedSkill:
    return ParsedSkill(
        name=name,
        description=description,
        location=location,
        base_dir=base_dir,
        source_scope=source_scope,
        body=body,
    )


class TestPromptComposition:
    """Test that skill prompts integrate correctly with compose_system_prompt."""

    def test_backward_compat_no_skill_params(self):
        """compose_system_prompt works without skill params (backward compat)."""
        prompt = compose_system_prompt(
            identity_prompt="You are a helpful agent.",
            focus_prompt="Focus on the task.",
        )
        assert "You are a helpful agent." in prompt
        assert "Focus on the task." in prompt
        assert "Current date and time" in prompt

    def test_skills_catalog_in_prompt(self):
        catalog = SkillCatalog([_make_skill(source_scope="project")])
        catalog_prompt = catalog.to_prompt()

        prompt = compose_system_prompt(
            identity_prompt="You are an agent.",
            focus_prompt=None,
            skills_catalog_prompt=catalog_prompt,
        )
        assert "<available_skills>" in prompt
        assert "<name>test-skill</name>" in prompt

    def test_protocols_in_prompt(self):
        manager = DefaultSkillManager()
        manager.load()
        protocols_prompt = manager.build_protocols_prompt()

        prompt = compose_system_prompt(
            identity_prompt="You are an agent.",
            focus_prompt=None,
            protocols_prompt=protocols_prompt,
        )
        assert "## Operational Protocols" in prompt

    def test_full_prompt_ordering(self):
        """Verify the three-layer onion ordering with all sections present."""
        catalog = SkillCatalog([_make_skill(source_scope="project")])

        prompt = compose_system_prompt(
            identity_prompt="IDENTITY_SECTION",
            focus_prompt="FOCUS_SECTION",
            narrative="NARRATIVE_SECTION",
            accounts_prompt="ACCOUNTS_SECTION",
            skills_catalog_prompt=catalog.to_prompt(),
            protocols_prompt="PROTOCOLS_SECTION",
        )

        identity_pos = prompt.index("IDENTITY_SECTION")
        accounts_pos = prompt.index("ACCOUNTS_SECTION")
        skills_pos = prompt.index("available_skills")
        protocols_pos = prompt.index("PROTOCOLS_SECTION")
        narrative_pos = prompt.index("NARRATIVE_SECTION")
        focus_pos = prompt.index("FOCUS_SECTION")

        # Identity → Accounts → Skills → Protocols → Narrative → Focus
        assert identity_pos < accounts_pos
        assert accounts_pos < skills_pos
        assert skills_pos < protocols_pos
        assert protocols_pos < narrative_pos
        assert narrative_pos < focus_pos

    def test_none_skill_prompts_excluded(self):
        """None values for skill prompts should not add content."""
        prompt = compose_system_prompt(
            identity_prompt="Hello",
            focus_prompt=None,
            skills_catalog_prompt=None,
            protocols_prompt=None,
        )
        assert "available_skills" not in prompt
        assert "Operational Protocols" not in prompt

    def test_empty_skill_prompts_excluded(self):
        """Empty string skill prompts should not add content."""
        prompt = compose_system_prompt(
            identity_prompt="Hello",
            focus_prompt=None,
            skills_catalog_prompt="",
            protocols_prompt="",
        )
        assert "available_skills" not in prompt
        assert "Operational Protocols" not in prompt


class TestEndToEndPipeline:
    """Test the full discovery → catalog → prompt pipeline."""

    def test_discovery_to_catalog_to_prompt(self, tmp_path):
        # Create a project skill
        skill_dir = tmp_path / ".agents" / "skills" / "my-tool"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-tool\ndescription: Tool for testing.\n---\n\n"
            "## Usage\nUse this tool when testing.\n",
            encoding="utf-8",
        )

        # Discovery
        discovery = SkillDiscovery(
            DiscoveryConfig(
                project_root=tmp_path,
                skip_user_scope=True,
                skip_framework_scope=True,
            )
        )
        skills = discovery.discover()
        assert len(skills) == 1

        # Catalog
        catalog = SkillCatalog(skills)
        assert catalog.skill_count == 1

        # Prompt generation
        prompt = catalog.to_prompt()
        assert "<name>my-tool</name>" in prompt
        assert "<description>Tool for testing.</description>" in prompt

        # Pre-activation
        activated = catalog.build_pre_activated_prompt(["my-tool"])
        assert "## Usage" in activated
        assert catalog.is_activated("my-tool")

    def test_defaults_plus_community_skills(self, tmp_path):
        """Default skills and community skills produce separate prompt sections."""
        # Create a community skill
        skill_dir = tmp_path / ".agents" / "skills" / "community-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: community-skill\ndescription: A community skill.\n---\n\nDo stuff.\n",
            encoding="utf-8",
        )

        # Discover community skills
        discovery = SkillDiscovery(
            DiscoveryConfig(
                project_root=tmp_path,
                skip_user_scope=True,
                skip_framework_scope=True,
            )
        )
        community_skills = discovery.discover()
        catalog = SkillCatalog(community_skills)
        catalog_prompt = catalog.to_prompt()

        # Load default skills
        manager = DefaultSkillManager()
        manager.load()
        protocols_prompt = manager.build_protocols_prompt()

        # Compose
        prompt = compose_system_prompt(
            identity_prompt="Agent identity.",
            focus_prompt=None,
            skills_catalog_prompt=catalog_prompt,
            protocols_prompt=protocols_prompt,
        )

        # Both sections present
        assert "<available_skills>" in prompt
        assert "<name>community-skill</name>" in prompt
        assert "## Operational Protocols" in prompt

    def test_config_disables_defaults_keeps_community(self, tmp_path):
        """Disabling all defaults should still allow community skills."""
        skill_dir = tmp_path / ".agents" / "skills" / "still-here"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: still-here\ndescription: Survives config.\n---\n\nBody.\n",
            encoding="utf-8",
        )

        # Community skills
        discovery = SkillDiscovery(
            DiscoveryConfig(
                project_root=tmp_path,
                skip_user_scope=True,
                skip_framework_scope=True,
            )
        )
        catalog = SkillCatalog(discovery.discover())

        # Disabled defaults
        config = SkillsConfig(all_defaults_disabled=True)
        manager = DefaultSkillManager(config)
        manager.load()

        catalog_prompt = catalog.to_prompt()
        protocols_prompt = manager.build_protocols_prompt()

        assert "<name>still-here</name>" in catalog_prompt
        assert protocols_prompt == ""
