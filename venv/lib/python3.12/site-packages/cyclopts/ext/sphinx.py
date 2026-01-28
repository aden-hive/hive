"""Sphinx extension for automatic Cyclopts CLI documentation."""

from typing import TYPE_CHECKING, Any

import attrs

from cyclopts import __version__
from cyclopts.utils import import_app

if TYPE_CHECKING:
    from sphinx.application import Sphinx

from docutils import nodes
from sphinx.application import Sphinx
from sphinx.util import logging
from sphinx.util.docutils import SphinxDirective

logger = logging.getLogger(__name__)


@attrs.define(kw_only=True)
class DirectiveOptions:
    """Configuration for the Cyclopts directive."""

    heading_level: int = 2
    max_heading_level: int = 6
    commands: list[str] | None = None
    exclude_commands: list[str] | None = None

    # All booleans must have ``False`` default.
    no_recursive: bool = False
    include_hidden: bool = False
    flatten_commands: bool = False
    code_block_title: bool = False
    skip_preamble: bool = False

    @classmethod
    def from_dict(cls, options: dict) -> "DirectiveOptions":
        """Create options from directive options dictionary."""
        kwargs = {}
        for field in attrs.fields(cls):
            # Convert underscore to dash for looking up in options
            option_name = field.name.replace("_", "-")

            if field.type is bool:
                # For boolean fields using directives.flag, presence means True
                # The value is None when present, absent from dict when not specified
                if option_name in options:
                    kwargs[field.name] = True
                # Use default value if not specified
            elif option_name in options:
                value = options[option_name]
                # Handle comma-separated lists for commands and exclude-commands
                if field.name in ("commands", "exclude_commands"):
                    # Parse comma-separated list and strip whitespace
                    if value:
                        kwargs[field.name] = [cmd.strip() for cmd in value.split(",") if cmd.strip()]
                    else:
                        # Empty string means empty list
                        kwargs[field.name] = []
                else:
                    kwargs[field.name] = value
            # If not specified, the dataclass default will be used

        return cls(**kwargs)

    @staticmethod
    def spec() -> dict[str, Any]:
        """Generate Sphinx option_spec from DirectiveOptions fields."""
        from docutils.parsers.rst import directives

        type_mapping = {
            bool: directives.flag,
            int: directives.nonnegative_int,
            str: directives.unchanged,
        }

        option_spec = {}
        for field in attrs.fields(DirectiveOptions):
            option_name = field.name.replace("_", "-")
            # Handle List[str] fields (commands, exclude-commands)
            if field.name in ("commands", "exclude_commands"):
                validator = directives.unchanged  # Will be parsed as comma-separated in from_dict
            else:
                validator = type_mapping.get(field.type, directives.unchanged)
            option_spec[option_name] = validator

        return option_spec


def _should_include_command(
    command_name: str,
    command_path: list[str],
    commands_filter: list[str] | None,
    exclude_commands: list[str] | None,
) -> bool:
    """Check if a command should be included in documentation.

    Parameters
    ----------
    command_name : str
        The name of the command.
    command_path : list[str]
        The full path to the command (including parent commands).
    commands_filter : list[str] | None
        If specified, only include commands in this list.
    exclude_commands : list[str] | None
        If specified, exclude commands in this list.

    Returns
    -------
    bool
        True if the command should be included.
    """
    # Build the full command path for nested commands
    full_path = ".".join(command_path + [command_name])

    # Check exclusion list first
    if exclude_commands:
        # Check both the command name and full path
        if command_name in exclude_commands or full_path in exclude_commands:
            return False
        # Check if any parent path is excluded
        for i in range(len(command_path)):
            parent_path = ".".join(command_path[: i + 1])
            if parent_path in exclude_commands:
                return False

    # Check inclusion list
    if commands_filter is not None:
        # If a filter is specified, only include if explicitly listed
        # Check if command name or full path is in the filter
        if command_name in commands_filter or full_path in commands_filter:
            return True
        # Check if any parent path is included (to include all subcommands)
        for i in range(len(command_path)):
            parent_path = ".".join(command_path[: i + 1])
            if parent_path in commands_filter:
                return True
        # Also check if just the base command name matches for top-level commands
        if not command_path and command_name in commands_filter:
            return True
        return False

    # No filter specified, include by default
    return True


def _filter_commands(
    commands: dict,
    commands_filter: list[str] | None,
    exclude_commands: list[str] | None,
    parent_path: list[str] | None = None,
) -> dict:
    """Filter commands based on inclusion/exclusion lists.

    Parameters
    ----------
    commands : dict
        Dictionary mapping command names to App instances.
    commands_filter : Optional[List[str]]
        If specified, only include commands in this list.
    exclude_commands : Optional[List[str]]
        If specified, exclude commands in this list.
    parent_path : List[str]
        Path to the parent command for nested commands.

    Returns
    -------
    dict
        Filtered commands dictionary.
    """
    if parent_path is None:
        parent_path = []

    filtered = {}
    for name, app in commands.items():
        if _should_include_command(name, parent_path, commands_filter, exclude_commands):
            filtered[name] = app

    return filtered


def _process_rst_content(content: str, skip_title: bool = False) -> list[str]:
    """Process RST content to remove problematic elements."""
    lines = content.splitlines()
    processed = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Skip title and underline if requested
        if skip_title and i == 0 and line.strip() and i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if next_line and set(next_line) <= {"-", "=", "^", "~", '"'}:
                i += 2
                continue

        # Skip .. contents:: directive
        if line.strip().startswith(".. contents::"):
            i += 1
            while i < len(lines) and lines[i].strip() and lines[i][0] in " \t":
                i += 1
            if i < len(lines) and not lines[i].strip():
                i += 1
            continue

        processed.append(line)
        i += 1

    return processed


def _create_section_nodes(lines: list[str], state: Any) -> list["nodes.Node"]:
    """Create section nodes from RST lines."""
    from docutils.statemachine import StringList

    result = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Check for section header
        if i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if next_line and all(c == "-" for c in next_line):
                # Create section
                section = nodes.section()
                title_text = line.strip()
                section["ids"] = [title_text.lower().replace(" ", "-").replace("cyclopts-", "cli-cyclopts-")]

                section += nodes.title(text=title_text)

                # Collect section content
                content_lines = []
                i += 2  # Skip title and underline

                while i < len(lines):
                    next_line_stripped = lines[i + 1].strip() if i + 1 < len(lines) else ""
                    if next_line_stripped and all(c == "-" for c in next_line_stripped):
                        break
                    content_lines.append(lines[i])
                    i += 1

                if content_lines:
                    state.nested_parse(StringList(content_lines), 0, section)

                result.append(section)
                continue

        # Check for literal block (::)
        if line.strip() == "::":
            # Skip the :: line
            i += 1

            # Skip blank line after ::
            if i < len(lines) and not lines[i].strip():
                i += 1

            # Collect indented content for the literal block
            literal_content = []
            while i < len(lines) and lines[i].startswith("    "):
                # Remove the 4-space indentation
                literal_content.append(lines[i][4:])
                i += 1

            # Create a literal block node directly
            if literal_content:
                literal_block = nodes.literal_block()
                literal_block.rawsource = "\n".join(literal_content)
                literal_block.append(nodes.Text("\n".join(literal_content)))
                result.append(literal_block)

            # Skip any trailing blank line
            if i < len(lines) and not lines[i].strip():
                i += 1

            continue

        # Regular content - accumulate consecutive lines
        if line.strip():
            content_lines = [line]
            i += 1

            # Collect consecutive non-empty lines that aren't section headers or literal blocks
            while i < len(lines):
                # Check if this is a section header
                next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
                if next_line and all(c == "-" for c in next_line):
                    break

                # Check if this is a literal block
                if lines[i].strip() == "::":
                    break

                # Check if this is a blank line
                if not lines[i].strip():
                    # Include the blank line and continue to see if there's more content
                    content_lines.append(lines[i])
                    i += 1
                    # If the next line is also blank or we're at the end, stop
                    if i >= len(lines) or not lines[i].strip():
                        break
                else:
                    # Add non-empty line
                    content_lines.append(lines[i])
                    i += 1

            # Parse all accumulated lines together
            para = nodes.paragraph()
            state.nested_parse(StringList(content_lines), 0, para)
            if para.children:
                result.extend(para.children)
        else:
            i += 1

    return result


class CycloptsDirective(SphinxDirective):  # type: ignore[misc,valid-type]
    """Sphinx directive for documenting Cyclopts CLI applications."""

    has_content = False
    required_arguments = 1
    optional_arguments = 0
    final_argument_whitespace = False
    option_spec = DirectiveOptions.spec()

    def run(self) -> list["nodes.Node"]:
        """Generate documentation nodes for the Cyclopts app."""
        module_path = self.arguments[0]
        opts = DirectiveOptions.from_dict(self.options)

        try:
            rst_content = self._generate_documentation(module_path, opts)
            return self._create_nodes(rst_content, opts)
        except Exception as e:
            return self._error_node(f"Error generating Cyclopts documentation: {e}")

    def _generate_documentation(self, module_path: str, opts: DirectiveOptions) -> str:
        """Generate RST documentation for the app."""
        from cyclopts.docs.rst import generate_rst_docs

        app = import_app(module_path)

        # Call generate_rst_docs directly to access internal no_root_title parameter
        return generate_rst_docs(
            app,
            recursive=not opts.no_recursive,
            include_hidden=opts.include_hidden,
            heading_level=opts.heading_level,
            max_heading_level=opts.max_heading_level,
            flatten_commands=opts.flatten_commands,
            commands_filter=opts.commands,
            exclude_commands=opts.exclude_commands,
            no_root_title=True,  # Always skip root title in Sphinx context
            code_block_title=opts.code_block_title,
            skip_preamble=opts.skip_preamble,
        )

    def _create_nodes(self, rst_content: str, opts: DirectiveOptions) -> list["nodes.Node"]:
        """Create docutils nodes from RST content."""
        lines = _process_rst_content(rst_content, skip_title=False)  # Title already skipped in generate_docs

        # Always use section nodes for better Sphinx integration
        return _create_section_nodes(lines, self.state)

    def _error_node(self, message: str) -> list["nodes.Node"]:
        """Create an error node with the given message."""
        logger.error(message)
        return [nodes.error("", nodes.paragraph(text=message))]


def setup(app: "Sphinx") -> dict[str, Any]:
    """Setup function for the Sphinx extension."""
    app.add_directive("cyclopts", CycloptsDirective)
    return {
        "version": __version__,
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
