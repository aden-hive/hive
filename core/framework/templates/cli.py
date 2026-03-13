"""CLI commands for the Hive template library."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from framework.templates.models import TemplateCategory
from framework.templates.registry import TemplateRegistry, get_template_registry


def register_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register template commands with the main CLI."""

    template_parser = subparsers.add_parser(
        "template",
        help="Manage agent templates",
        description="Browse, search, and copy agent templates from the Hive library.",
    )
    template_subparsers = template_parser.add_subparsers(dest="template_command", required=True)

    list_parser = template_subparsers.add_parser(
        "list",
        help="List available templates",
        description="List all templates or filter by category/tag.",
    )
    list_parser.add_argument(
        "--category",
        "-c",
        type=str,
        help="Filter by category (sales, support, ops, research, growth, productivity, development, hr, finance, marketing)",
    )
    list_parser.add_argument(
        "--tag",
        "-t",
        type=str,
        help="Filter by tag",
    )
    list_parser.add_argument(
        "--search",
        "-s",
        type=str,
        help="Search templates by name, description, or tags",
    )
    list_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    list_parser.set_defaults(func=cmd_template_list)

    show_parser = template_subparsers.add_parser(
        "show",
        help="Show template details",
        description="Display detailed information about a specific template.",
    )
    show_parser.add_argument(
        "template_id",
        type=str,
        help="Template ID (directory name)",
    )
    show_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    show_parser.set_defaults(func=cmd_template_show)

    copy_parser = template_subparsers.add_parser(
        "copy",
        help="Copy a template",
        description="Copy a template to your exports directory or a custom location.",
    )
    copy_parser.add_argument(
        "template_id",
        type=str,
        help="Template ID to copy",
    )
    copy_parser.add_argument(
        "destination",
        type=str,
        nargs="?",
        default="exports",
        help="Destination directory (default: exports)",
    )
    copy_parser.add_argument(
        "--name",
        "-n",
        type=str,
        help="New name for the copied template",
    )
    copy_parser.set_defaults(func=cmd_template_copy)

    categories_parser = template_subparsers.add_parser(
        "categories",
        help="List template categories",
        description="List all available template categories.",
    )
    categories_parser.set_defaults(func=cmd_template_categories)

    tags_parser = template_subparsers.add_parser(
        "tags",
        help="List template tags",
        description="List all unique tags used across templates.",
    )
    tags_parser.set_defaults(func=cmd_template_tags)


def cmd_template_list(args: argparse.Namespace) -> int:
    """List available templates."""
    registry = get_template_registry()

    templates = []

    if args.search:
        templates = registry.search(args.search)
    elif args.category:
        try:
            category = TemplateCategory.from_string(args.category)
            templates = registry.list_by_category(category)
        except ValueError:
            print(f"Invalid category: {args.category}", file=sys.stderr)
            print(f"Valid categories: {', '.join(c.value for c in TemplateCategory)}")
            return 1
    elif args.tag:
        templates = registry.list_by_tag(args.tag)
    else:
        templates = registry.discover_templates()

    if not templates:
        print("No templates found.")
        return 0

    if args.json:
        import json

        output = [t.to_dict() for t in templates]
        print(json.dumps(output, indent=2))
        return 0

    print(f"\nFound {len(templates)} template(s):\n")

    for template in templates:
        print(f"  {template.name} ({template.id})")
        print(f"    Category: {template.category.display_name()}")
        desc = template.description
        if len(desc) > 60:
            desc = desc[:60] + "..."
        print(f"    Description: {desc}")
        if template.tags:
            tags_str = ", ".join(template.tags[:5])
            if len(template.tags) > 5:
                tags_str += f" (+{len(template.tags) - 5} more)"
            print(f"    Tags: {tags_str}")
        print(f"    Nodes: {template.node_count}, Tools: {template.tool_count}")
        print()

    return 0


def cmd_template_show(args: argparse.Namespace) -> int:
    """Show details for a specific template."""
    registry = get_template_registry()
    template = registry.get_template(args.template_id)

    if template is None:
        print(f"Template not found: {args.template_id}", file=sys.stderr)
        return 1

    if args.json:
        import json

        print(json.dumps(template.to_dict(), indent=2))
        return 0

    print(f"\n{template.name}")
    print("=" * len(template.name))
    print(f"\nID: {template.id}")
    print(f"Category: {template.category.display_name()}")
    print(f"Version: {template.version}")
    print(f"Author: {template.author}")
    print(f"\nDescription:\n  {template.description}")

    if template.tags:
        print(f"\nTags: {', '.join(template.tags)}")

    print(f"\nStructure:")
    print(f"  Nodes: {template.node_count}")
    print(f"  Tools: {template.tool_count}")

    if template.required_tools:
        print(f"\nRequired Tools:")
        for tool in template.required_tools:
            print(f"  - {tool}")

    if template.path:
        print(f"\nPath: {template.path}")
        print(f"\nUsage:")
        print(f"  hive run {template.path}")
        print(f"  hive template copy {template.id}")

    print()

    return 0


def cmd_template_copy(args: argparse.Namespace) -> int:
    """Copy a template to a new location."""
    import shutil

    registry = get_template_registry()
    template = registry.get_template(args.template_id)

    if template is None:
        print(f"Template not found: {args.template_id}", file=sys.stderr)
        return 1

    destination = Path(args.destination)

    if not destination.is_absolute():
        project_root = Path.cwd()
        while project_root.parent != project_root:
            if (project_root / "core").is_dir():
                break
            project_root = project_root.parent
        destination = project_root / destination

    try:
        dest_path = registry.copy_template(args.template_id, destination, args.name)
        if dest_path is None:
            print(f"Failed to copy template: {args.template_id}", file=sys.stderr)
            return 1

        print(f"Copied template to: {dest_path}")
        print(f"\nYou can now customize and run it:")
        print(f"  cd {dest_path}")
        print(f'  hive run . --input \'{{"key": "value"}}\'')

        return 0

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Failed to copy template: {e}", file=sys.stderr)
        return 1


def cmd_template_categories(args: argparse.Namespace) -> int:
    """List all template categories."""
    registry = get_template_registry()
    categories = registry.get_categories()

    print("\nAvailable Categories:\n")

    for category in categories:
        count = len(registry.list_by_category(category))
        print(f"  {category.display_name():<15} ({count} templates)")

    print()

    return 0


def cmd_template_tags(args: argparse.Namespace) -> int:
    """List all template tags."""
    registry = get_template_registry()
    tags = registry.get_all_tags()

    if not tags:
        print("No tags found.")
        return 0

    print("\nAvailable Tags:\n")

    for tag in tags:
        count = len(registry.list_by_tag(tag))
        print(f"  {tag} ({count} templates)")

    print()

    return 0
