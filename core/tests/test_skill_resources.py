"""Tests for AS-6 skill resource loading support.

Covers:
- <base_dir> element in catalog XML
- allowlisted_dirs property reflects trusted skill base directories
- skill_dirs propagation to NodeContext
"""

from framework.skills.catalog import SkillCatalog
from framework.skills.parser import ParsedSkill


def _make_skill(
    name: str,
    base_dir: str,
    source_scope: str = "project",
) -> ParsedSkill:
    return ParsedSkill(
        name=name,
        description=f"Skill {name}",
        location=f"{base_dir}/SKILL.md",
        base_dir=base_dir,
        source_scope=source_scope,
        body="Instructions.",
    )


class TestSkillResourceBaseDir:
    def test_base_dir_in_xml(self):
        """Each community skill entry should expose its base_dir in the catalog XML."""
        skill = _make_skill("deploy", "/project/.hive/skills/deploy")
        catalog = SkillCatalog([skill])
        prompt = catalog.to_prompt()

        assert "<base_dir>/project/.hive/skills/deploy</base_dir>" in prompt

    def test_base_dir_xml_escaped(self):
        """base_dir with XML-special chars should be escaped."""
        skill = _make_skill("s", "/path/with <&> chars")
        catalog = SkillCatalog([skill])
        prompt = catalog.to_prompt()

        assert "<base_dir>/path/with &lt;&amp;&gt; chars</base_dir>" in prompt

    def test_base_dir_absent_for_framework_skills(self):
        """Framework-scope skills are filtered from the catalog, so no base_dir either."""
        skill = _make_skill("fw", "/hive/_default_skills/fw", source_scope="framework")
        catalog = SkillCatalog([skill])
        assert catalog.to_prompt() == ""

    def test_allowlisted_dirs_matches_skills(self):
        """allowlisted_dirs returns all skill base_dirs including framework ones."""
        skills = [
            _make_skill("a", "/skills/a", "project"),
            _make_skill("b", "/skills/b", "user"),
            _make_skill("c", "/skills/c", "framework"),
        ]
        catalog = SkillCatalog(skills)
        dirs = catalog.allowlisted_dirs

        assert "/skills/a" in dirs
        assert "/skills/b" in dirs
        assert "/skills/c" in dirs

    def test_allowlisted_dirs_empty_catalog(self):
        assert SkillCatalog().allowlisted_dirs == []


class TestSkillDirsPropagation:
    def _make_ctx(self, **kwargs):
        from unittest.mock import MagicMock

        from framework.graph.node import NodeContext

        return NodeContext(
            runtime=MagicMock(),
            node_id="n",
            node_spec=MagicMock(),
            memory={},
            **kwargs,
        )

    def test_node_context_skill_dirs_default(self):
        """NodeContext.skill_dirs defaults to empty list."""
        ctx = self._make_ctx()
        assert ctx.skill_dirs == []

    def test_node_context_skill_dirs_set(self):
        """NodeContext.skill_dirs can be populated."""
        dirs = ["/skills/a", "/skills/b"]
        ctx = self._make_ctx(skill_dirs=dirs)
        assert ctx.skill_dirs == dirs
