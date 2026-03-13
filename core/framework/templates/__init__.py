"""Hive Template Library.

Browse, search, and copy agent templates from the Hive community library.

Example usage:
    from framework.templates import TemplateRegistry, TemplateCategory

    registry = TemplateRegistry()
    templates = registry.discover_templates()

    # Filter by category
    sales_templates = registry.list_by_category(TemplateCategory.SALES)

    # Search templates
    results = registry.search("email")

    # Get a specific template
    template = registry.get_template("job_hunter")
"""

from framework.templates.models import TemplateCategory, TemplateMetadata
from framework.templates.registry import TemplateRegistry, get_template_registry

__all__ = [
    "TemplateCategory",
    "TemplateMetadata",
    "TemplateRegistry",
    "get_template_registry",
]
