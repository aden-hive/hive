"""Template registry for discovering and querying Hive templates."""

from __future__ import annotations

import json
from pathlib import Path

from framework.templates.models import TemplateCategory, TemplateMetadata


class TemplateRegistry:
    """Registry for discovering and querying Hive agent templates."""

    def __init__(self, templates_dir: Path | None = None):
        """Initialize the template registry.

        Args:
            templates_dir: Directory containing templates. Defaults to
                examples/templates/ relative to this file.
        """
        if templates_dir is None:
            framework_dir = Path(__file__).resolve().parent.parent
            templates_dir = framework_dir.parent.parent / "examples" / "templates"
        self.templates_dir = templates_dir
        self._cache: list[TemplateMetadata] | None = None

    def discover_templates(self, force_reload: bool = False) -> list[TemplateMetadata]:
        """Discover all available templates.

        Args:
            force_reload: Force reload from disk, ignoring cache.

        Returns:
            List of TemplateMetadata for all discovered templates.
        """
        if self._cache is not None and not force_reload:
            return self._cache

        templates: list[TemplateMetadata] = []

        if not self.templates_dir.exists():
            return templates

        for template_path in sorted(self.templates_dir.iterdir()):
            if not template_path.is_dir():
                continue

            metadata = self._load_template_metadata(template_path)
            if metadata:
                templates.append(metadata)

        self._cache = templates
        return templates

    def _load_template_metadata(self, template_path: Path) -> TemplateMetadata | None:
        """Load metadata for a single template.

        Args:
            template_path: Path to the template directory.

        Returns:
            TemplateMetadata if valid template, None otherwise.
        """
        agent_json = template_path / "agent.json"
        agent_py = template_path / "agent.py"
        template_json = template_path / "template.json"

        if not (agent_json.exists() or agent_py.exists()):
            return None

        template_id = template_path.name
        name = template_id.replace("_", " ").title()
        description = ""
        category = TemplateCategory.GENERAL
        tags: list[str] = []
        author = "Hive Team"
        version = "1.0.0"
        node_count = 0
        tool_count = 0
        required_tools: list[str] = []

        if template_json.exists():
            try:
                data = json.loads(template_json.read_text(encoding="utf-8"))
                name = data.get("name", name)
                description = data.get("description", "")
                category = TemplateCategory.from_string(data.get("category", "general"))
                tags = data.get("tags", [])
                author = data.get("author", author)
                version = data.get("version", version)
            except (json.JSONDecodeError, OSError):
                pass

        if agent_json.exists():
            try:
                data = json.loads(agent_json.read_text(encoding="utf-8"))
                agent_data = data.get("agent", {})
                graph_data = data.get("graph", {})

                if not name or name == template_id.replace("_", " ").title():
                    name = agent_data.get("name", name)
                if not description:
                    description = agent_data.get("description", "")

                nodes = graph_data.get("nodes", [])
                node_count = len(nodes)

                tools: set[str] = set()
                for node in nodes:
                    node_tools = node.get("tools", [])
                    if isinstance(node_tools, list):
                        tools.update(node_tools)
                tool_count = len(tools)
                required_tools = list(tools)

                if not tags:
                    tags = agent_data.get("tags", [])

            except (json.JSONDecodeError, OSError):
                pass

        if not description:
            description = f"A {category.display_name().lower()} agent template."

        return TemplateMetadata(
            id=template_id,
            name=name,
            description=description,
            category=category,
            tags=tags,
            author=author,
            version=version,
            node_count=node_count,
            tool_count=tool_count,
            required_tools=required_tools,
            path=template_path,
        )

    def get_template(self, template_id: str) -> TemplateMetadata | None:
        """Get a specific template by ID.

        Args:
            template_id: The template identifier (directory name).

        Returns:
            TemplateMetadata if found, None otherwise.
        """
        templates = self.discover_templates()
        for template in templates:
            if template.id == template_id:
                return template
        return None

    def list_by_category(self, category: TemplateCategory) -> list[TemplateMetadata]:
        """List templates filtered by category.

        Args:
            category: The category to filter by.

        Returns:
            List of templates in the specified category.
        """
        templates = self.discover_templates()
        return [t for t in templates if t.category == category]

    def list_by_tag(self, tag: str) -> list[TemplateMetadata]:
        """List templates filtered by tag.

        Args:
            tag: The tag to filter by.

        Returns:
            List of templates with the specified tag.
        """
        templates = self.discover_templates()
        tag_lower = tag.lower()
        return [t for t in templates if tag_lower in [t.lower() for t in t.tags]]

    def search(self, query: str) -> list[TemplateMetadata]:
        """Search templates by name, description, or tags.

        Args:
            query: Search query string.

        Returns:
            List of matching templates.
        """
        templates = self.discover_templates()
        query_lower = query.lower()

        results = []
        for template in templates:
            if (
                query_lower in template.name.lower()
                or query_lower in template.description.lower()
                or any(query_lower in tag.lower() for tag in template.tags)
            ):
                results.append(template)

        return results

    def get_categories(self) -> list[TemplateCategory]:
        """Get list of categories that have templates.

        Returns:
            List of categories with at least one template.
        """
        templates = self.discover_templates()
        categories = set(t.category for t in templates)
        return sorted(categories, key=lambda c: c.value)

    def get_all_tags(self) -> list[str]:
        """Get list of all unique tags across templates.

        Returns:
            Sorted list of unique tags.
        """
        templates = self.discover_templates()
        tags = set()
        for template in templates:
            tags.update(template.tags)
        return sorted(tags)

    def copy_template(
        self, template_id: str, destination: Path, new_name: str | None = None
    ) -> Path | None:
        """Copy a template to a new location.

        Args:
            template_id: The template to copy.
            destination: Destination directory.
            new_name: Optional new name for the copied template.

        Returns:
            Path to the copied template, or None if template not found.
        """
        import shutil

        template = self.get_template(template_id)
        if template is None or template.path is None:
            return None

        dest_name = new_name or template_id
        dest_path = destination / dest_name

        if dest_path.exists():
            raise ValueError(f"Destination already exists: {dest_path}")

        shutil.copytree(template.path, dest_path)
        return dest_path


def get_template_registry() -> TemplateRegistry:
    """Get the global template registry instance.

    Returns:
        TemplateRegistry instance.
    """
    return TemplateRegistry()
