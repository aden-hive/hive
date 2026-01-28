"""MkDocs plugin for automatic Cyclopts CLI documentation."""

import re
from typing import TYPE_CHECKING, Any

import yaml
from attrs import define, field, validators

from cyclopts.docs.markdown import generate_markdown_docs
from cyclopts.utils import import_app

if TYPE_CHECKING:
    from mkdocs.config.defaults import MkDocsConfig
    from mkdocs.structure.files import Files
    from mkdocs.structure.pages import Page

from mkdocs.config import base
from mkdocs.config import config_options as c
from mkdocs.exceptions import PluginError
from mkdocs.plugins import BasePlugin, get_plugin_logger

logger = get_plugin_logger(__name__)


@define(kw_only=True)
class DirectiveOptions:
    """Configuration for the ::: cyclopts directive."""

    module: str = field(validator=validators.instance_of(str))
    heading_level: int = field(default=2, validator=validators.instance_of(int))
    max_heading_level: int = field(default=6, validator=validators.instance_of(int))
    commands: list[str] | None = field(default=None, validator=validators.optional(validators.instance_of(list)))
    exclude_commands: list[str] | None = field(
        default=None, validator=validators.optional(validators.instance_of(list))
    )
    recursive: bool = field(default=True, validator=validators.instance_of(bool))
    include_hidden: bool = field(default=False, validator=validators.instance_of(bool))
    flatten_commands: bool = field(default=False, validator=validators.instance_of(bool))
    generate_toc: bool = field(default=True, validator=validators.instance_of(bool))
    code_block_title: bool = field(default=False, validator=validators.instance_of(bool))
    skip_preamble: bool = field(default=False, validator=validators.instance_of(bool))

    @classmethod
    def from_directive_block(
        cls,
        directive_text: str,
        *,
        default_heading_level: int | None = None,
        default_max_heading_level: int | None = None,
    ) -> "DirectiveOptions":
        """Parse options from a ::: cyclopts directive block.

        Expected format:
            ::: cyclopts
                module: myapp.cli:app
                heading_level: 2
                max_heading_level: 6
                recursive: true
                commands:
                  - cmd1
                  - cmd2

        Parameters
        ----------
        directive_text : str
            The directive text to parse.
        default_heading_level : int | None
            Default heading level from plugin config. Used if :heading-level: not specified.
        default_max_heading_level : int | None
            Default max heading level from plugin config. Used if :max-heading-level: not specified.
        """
        lines = directive_text.strip().split("\n")

        # Remove the ::: cyclopts line
        if lines and lines[0].strip().startswith("::: cyclopts"):
            lines = lines[1:]

        yaml_content = "\n".join(lines)
        options = yaml.safe_load(yaml_content) or {}

        if not isinstance(options, dict):
            raise TypeError("Invalid YAML in ::: cyclopts directive: expected a dictionary")

        if "module" not in options:
            raise ValueError('The "module" option is required for ::: cyclopts directive')

        if default_heading_level is not None:
            options.setdefault("heading_level", default_heading_level)

        if default_max_heading_level is not None:
            options.setdefault("max_heading_level", default_max_heading_level)

        # Convert keys with dashes to underscores
        normalized_options = {key.replace("-", "_"): value for key, value in options.items()}

        try:
            return cls(**normalized_options)
        except TypeError as e:
            raise ValueError(f"Error creating DirectiveOptions: {e}") from e


# Regex to match ::: cyclopts directive blocks
# The pattern matches:
# - "^::: cyclopts\n" - the directive start on its own line
# - "(?:[ \t]+.*\n?)*" - zero or more indented YAML lines (with optional trailing newline for EOF)
DIRECTIVE_PATTERN = re.compile(
    r"^::: cyclopts\n(?:[ \t]+.*\n?)*",
    re.MULTILINE,
)


def process_cyclopts_directives(markdown: str, plugin_config: Any) -> str:
    """Process all ::: cyclopts directives in markdown content.

    Parameters
    ----------
    markdown : str
        The markdown content containing ::: cyclopts directives.
    plugin_config : CycloptsPluginConfig
        The plugin configuration with default values. If None, uses DirectiveOptions defaults.

    Returns
    -------
    str
        The markdown content with directives replaced by generated documentation.
    """
    # Find all code blocks to exclude from processing
    code_blocks = []

    # Find fenced code blocks (triple backticks or tildes)
    fenced_pattern = re.compile(r"^[`~]{3,}.*?^[`~]{3,}", re.MULTILINE | re.DOTALL)
    for match in fenced_pattern.finditer(markdown):
        code_blocks.append((match.start(), match.end()))

    # Find indented code blocks (lines starting with 4 spaces or tab)
    # Indented code blocks are preceded by a blank line and consist of lines starting with 4 spaces/tab
    lines = markdown.split("\n")
    in_indented_block = False
    block_start = 0
    current_pos = 0

    for i, line in enumerate(lines):
        line_len = len(line) + 1  # +1 for the newline

        # Check if this line starts an indented code block
        if not in_indented_block:
            # Previous line must be blank (or be the first line)
            prev_blank = i == 0 or not lines[i - 1].strip()
            # Current line must start with 4 spaces or a tab and have content
            is_indented = (line.startswith("    ") or line.startswith("\t")) and line.strip()

            if prev_blank and is_indented:
                in_indented_block = True
                block_start = current_pos
        else:
            # Check if we're still in the indented block
            is_indented = (line.startswith("    ") or line.startswith("\t")) and line.strip()
            is_blank = not line.strip()

            # End block if we hit a non-indented, non-blank line
            if not is_indented and not is_blank:
                code_blocks.append((block_start, current_pos))
                in_indented_block = False

        current_pos += line_len

    # If we ended while still in an indented block, add it
    if in_indented_block:
        code_blocks.append((block_start, current_pos))

    def is_in_code_block(pos: int) -> bool:
        """Check if a position is inside a code block."""
        for start, end in code_blocks:
            if start <= pos < end:
                return True
        return False

    def replace_directive(match: re.Match) -> str:
        # Skip if this match is inside a code block
        if is_in_code_block(match.start()):
            return match.group(0)

        directive_text = match.group(0)

        try:
            default_heading = plugin_config.default_heading_level if plugin_config else None
            default_max_heading = plugin_config.default_max_heading_level if plugin_config else None
            options = DirectiveOptions.from_directive_block(
                directive_text,
                default_heading_level=default_heading,
                default_max_heading_level=default_max_heading,
            )

            app = import_app(options.module)

            markdown_docs = generate_markdown_docs(
                app,
                recursive=options.recursive,
                include_hidden=options.include_hidden,
                heading_level=options.heading_level,
                max_heading_level=options.max_heading_level,
                generate_toc=options.generate_toc,
                flatten_commands=options.flatten_commands,
                commands_filter=options.commands,
                exclude_commands=options.exclude_commands,
                no_root_title=True,  # Skip root title in plugin context
                code_block_title=options.code_block_title,
                skip_preamble=options.skip_preamble,
            )

            return markdown_docs

        except Exception as e:
            raise PluginError(f"Error processing ::: cyclopts directive: {e}") from e

    # Replace all directives in the markdown
    processed = DIRECTIVE_PATTERN.sub(replace_directive, markdown)
    return processed


class CycloptsPluginConfig(base.Config):  # type: ignore[misc]
    """Configuration schema for the Cyclopts MkDocs plugin."""

    default_heading_level = c.Type(int, default=2)  # type: ignore[attr-defined]
    default_max_heading_level = c.Type(int, default=6)  # type: ignore[attr-defined]


class CycloptsPlugin(BasePlugin[CycloptsPluginConfig]):  # type: ignore[misc]
    """MkDocs plugin to generate Cyclopts CLI documentation.

    Usage in mkdocs.yml:
        plugins:
          - cyclopts:
              default_heading_level: 2

    Usage in Markdown files:
        ::: cyclopts
            :module: myapp.cli:app
            :heading-level: 2
            :recursive: true
            :commands: init, build
            :exclude-commands: debug
    """

    def on_page_markdown(self, markdown: str, *, page: "Page", config: "MkDocsConfig", files: "Files", **kwargs) -> str:
        """Process ::: cyclopts directives in markdown content.

        This event is called after the page's markdown is loaded from file
        but before it's converted to HTML.
        """
        if "::: cyclopts" not in markdown:
            return markdown

        return process_cyclopts_directives(markdown, self.config)
