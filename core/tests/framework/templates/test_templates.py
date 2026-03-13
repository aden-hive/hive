"""Tests for the Hive template library."""

from __future__ import annotations

import pytest
from pathlib import Path

from framework.templates.models import TemplateCategory, TemplateMetadata
from framework.templates.registry import TemplateRegistry


class TestTemplateModels:
    """Tests for template metadata models."""

    def test_template_category_from_string(self):
        assert TemplateCategory.from_string("sales") == TemplateCategory.SALES
        assert TemplateCategory.from_string("SUPPORT") == TemplateCategory.SUPPORT
        assert TemplateCategory.from_string("research") == TemplateCategory.RESEARCH
        assert TemplateCategory.from_string("unknown") == TemplateCategory.GENERAL

        assert TemplateCategory.from_string("OPS") == TemplateCategory.OPS
        assert TemplateCategory.from_string("Productivity") == TemplateCategory.PRODUCTIVITY

        assert TemplateCategory.from_string("HR") == TemplateCategory.HR

        assert TemplateCategory.from_string("Finance") == TemplateCategory.FINANCE
        assert TemplateCategory.from_string("Marketing") == TemplateCategory.MARKETING

        assert TemplateCategory.from_string("Growth") == TemplateCategory.GROWTH
        assert TemplateCategory.from_string("Development") == TemplateCategory.DEVELOPMENT

        assert TemplateCategory.from_string("") == TemplateCategory.GENERAL
        assert TemplateCategory.from_string(None) == TemplateCategory.GENERAL

    def test_template_category_display_name(self):
        assert TemplateCategory.SALES.display_name() == "Sales"
        assert TemplateCategory.RESEARCH.display_name() == "Research"
        assert TemplateCategory.OPS.display_name() == "Ops"
        assert TemplateCategory.GROWTH.display_name() == "Growth"
        assert TemplateCategory.PRODUCTIVITY.display_name() == "Productivity"
        assert TemplateCategory.DEVELOPMENT.display_name() == "Development"
        assert TemplateCategory.HR.display_name() == "HR"
        assert TemplateCategory.FINANCE.display_name() == "Finance"
        assert TemplateCategory.MARKETING.display_name() == "Marketing"

        assert TemplateCategory.GENERAL.display_name() == "General"

    def test_template_metadata_to_dict(self):
        metadata = TemplateMetadata(
            id="test_agent",
            name="Test Agent",
            description="A test agent",
            category=TemplateCategory.RESEARCH,
            tags=["test", "demo"],
            author="Test Author",
            version="1.0.0",
            node_count=3,
            tool_count=2,
            required_tools=["web_search", "save_data"],
            popularity=100,
        )

        result = metadata.to_dict()

        assert result["id"] == "test_agent"
        assert result["name"] == "Test Agent"
        assert result["category"] == "research"
        assert result["tags"] == ["test", "demo"]
        assert result["node_count"] == 3
        assert result["tool_count"] == 2

        assert result["author"] == "Test Author"
        assert result["version"] == "1.0.0"
        assert result["popularity"] == 100

        assert result["required_tools"] == ["web_search", "save_data"]

    def test_template_metadata_from_dict(self):
        data = {
            "id": "from_dict_test",
            "name": "From Dict Test",
            "description": "Testing from_dict",
            "category": "productivity",
            "tags": ["unit-test"],
            "node_count": 1,
        }

        metadata = TemplateMetadata.from_dict(data)

        assert metadata.id == "from_dict_test"
        assert metadata.name == "From Dict Test"
        assert metadata.category == TemplateCategory.PRODUCTIVITY
        assert metadata.tags == ["unit-test"]
        assert metadata.node_count == 1
        assert metadata.author == "Hive Team"
        assert metadata.version == "1.0.0"

    def test_template_metadata_from_dict_with_none(self):
        metadata = TemplateMetadata.from_dict({})
        assert metadata.id == ""
        assert metadata.name == ""
        assert metadata.category == TemplateCategory.GENERAL

        assert metadata.tags == []


class TestTemplateRegistry:
    """Tests for TemplateRegistry class."""

    @pytest.fixture
    def registry(self, tmp_path: Path) -> TemplateRegistry:
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir(parents=True)

        valid_template = templates_dir / "valid_agent"
        valid_template.mkdir()
        (valid_template / "agent.json").write_text(
            '{"agent": {"name": "Valid Agent", "description": "A valid test agent"}}',
            encoding="utf-8",
        )
        (valid_template / "template.json").write_text(
            '{"name": "Valid Agent", "description": "A valid test agent", "category": "research", "tags": ["test"]}',
            encoding="utf-8",
        )

        empty_template = templates_dir / "empty_agent"
        empty_template.mkdir()
        (empty_template / "agent.json").write_text("{}", encoding="utf-8")

        no_metadata_template = templates_dir / "no_meta_agent"
        no_metadata_template.mkdir()
        (no_metadata_template / "agent.py").write_text("# placeholder", encoding="utf-8")

        template_with_tags = templates_dir / "tagged_agent"
        template_with_tags.mkdir()
        (template_with_tags / "agent.json").write_text(
            '{"agent": {"name": "Tagged Agent"}}',
            encoding="utf-8",
        )
        (template_with_tags / "template.json").write_text(
            '{"name": "Tagged Agent", "description": "Agent with tags", "category": "sales", "tags": ["sales", "lead-gen", "automation"]}',
            encoding="utf-8",
        )

        yield TemplateRegistry(templates_dir)

    def test_discover_templates(self, registry: TemplateRegistry):
        templates = registry.discover_templates()
        assert len(templates) == 4
        valid = next(t for t in templates if t.id == "valid_agent")
        assert valid is not None
        assert valid.name == "Valid Agent"
        assert valid.category == TemplateCategory.RESEARCH

        assert valid.tags == ["test"]
        tagged = next(t for t in templates if t.id == "tagged_agent")
        assert tagged is not None
        assert tagged.category == TemplateCategory.SALES
        assert set(tagged.tags) == {"sales", "lead-gen", "automation"}

    def test_get_template(self, registry: TemplateRegistry):
        template = registry.get_template("valid_agent")
        assert template is not None
        assert template.id == "valid_agent"
        assert registry.get_template("nonexistent") is None

    def test_list_by_category(self, registry: TemplateRegistry):
        research_templates = registry.list_by_category(TemplateCategory.RESEARCH)
        assert len(research_templates) == 1
        assert research_templates[0].id == "valid_agent"
        sales_templates = registry.list_by_category(TemplateCategory.SALES)
        assert len(sales_templates) == 1
        assert sales_templates[0].id == "tagged_agent"
        general_templates = registry.list_by_category(TemplateCategory.GENERAL)
        assert len(general_templates) == 2

    def test_list_by_tag(self, registry: TemplateRegistry):
        test_templates = registry.list_by_tag("test")
        assert len(test_templates) == 1
        assert test_templates[0].id == "valid_agent"
        sales_templates = registry.list_by_tag("sales")
        assert len(sales_templates) == 1
        assert sales_templates[0].id == "tagged_agent"
        assert len(registry.list_by_tag("nonexistent")) == 0
        automation_templates = registry.list_by_tag("automation")
        assert len(automation_templates) == 1

    def test_search(self, registry: TemplateRegistry):
        results = registry.search("valid")
        assert len(results) == 1
        assert results[0].id == "valid_agent"
        results = registry.search("test")
        assert len(results) == 1
        results = registry.search("sales")
        assert len(results) == 1
        assert results[0].id == "tagged_agent"
        assert len(registry.search("nonexistentxyz")) == 0

    def test_get_categories(self, registry: TemplateRegistry):
        categories = registry.get_categories()
        assert TemplateCategory.RESEARCH in categories
        assert TemplateCategory.SALES in categories
        assert TemplateCategory.GENERAL in categories
        assert len(categories) == 3

    def test_get_all_tags(self, registry: TemplateRegistry):
        tags = registry.get_all_tags()
        assert "test" in tags
        assert "sales" in tags
        assert "lead-gen" in tags
        assert "automation" in tags
        assert len(tags) == 4
