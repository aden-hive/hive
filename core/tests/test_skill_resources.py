"""Tests for AS-6 skill resource loading support.

Covers:
- allowlisted_dirs property reflects trusted skill base directories
- skill_dirs propagation to NodeContext

The catalog XML previously emitted a redundant <base_dir> element next to
each <location>. That was dropped when the mandatory header took over the
"resolve relative paths against the parent of SKILL.md" instruction, so
there is no longer an XML-emission test for base_dir. Programmatic access
via ``catalog.allowlisted_dirs`` is still covered below.
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

        from framework.orchestrator.node import NodeContext

        return NodeContext(
            runtime=MagicMock(),
            node_id="n",
            node_spec=MagicMock(),
            buffer={},
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
