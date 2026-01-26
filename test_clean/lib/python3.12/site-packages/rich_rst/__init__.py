# -*- coding: utf-8 -*-

"""
reStructuredText parser for rich

Initial few lines gotten from: https://github.com/willmcgugan/rich/discussions/1263#discussioncomment-808898
There are a lot of improvements are added by me
"""
from io import StringIO
from html.parser import HTMLParser
from typing import Optional, Union

# Imports from docutils package for the parsing
import docutils.io
import docutils.nodes
import docutils.parsers.rst
import docutils.utils

# Imports from the rich package for the printing
import rich
from rich import box
from rich.align import Align
from rich.console import Console, ConsoleOptions, RenderResult, NewLine
from rich.jupyter import JupyterMixin
from rich.panel import Panel
from rich.style import Style
from rich.syntax import Syntax, SyntaxTheme
from rich.text import Text
from rich.table import Table
from rich.traceback import install
from rich.rule import Rule

from pygments.lexers import guess_lexer
from pygments.util import ClassNotFound

__all__ = ("RST", "ReStructuredText", "reStructuredText", "RestructuredText")
__author__ = "Arian Mollik Wasi (aka. Wasi Master)"
__version__ = "1.3.2"

install()


class MLStripper(HTMLParser):
    """Utility class to strip out html for raw html source"""
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = StringIO()

    def handle_data(self, d):
        self.text.write(d)

    def get_data(self):
        return self.text.getvalue()


def strip_tags(html):
    s = MLStripper()
    s.feed(html)
    return s.get_data()


def _register_sphinx_roles():
    """
    Register common Sphinx roles to gracefully handle Sphinx-specific markup.

    Sphinx roles like :func:, :class:, :meth: are very common in Python docstrings
    but are not available in standard docutils. This function registers them to
    render as inline code/literal text instead of showing errors.
    """
    import docutils.parsers.rst.roles
    import docutils.parsers.rst.languages.en

    def sphinx_role(name, rawtext, text, lineno, inliner, options={}, content=[]):
        """
        Generic Sphinx role handler that renders as inline literal text.

        Parameters
        ----------
        name : str
            The role name
        rawtext : str
            The entire role text including role markup
        text : str
            The interpreted text content
        lineno : int
            The line number where the interpreted text begins
        inliner : Inliner
            The inliner instance that called this role function
        options : dict
            Directive options for customization
        content : list
            The directive content for customization

        Returns
        -------
        tuple
            A tuple of (nodes, messages)
        """
        display_text = text
        if '<' in text and text.endswith('>'):
            bracket_pos = text.rfind('<')
            potential_display = text[:bracket_pos].strip()
            if potential_display:
                display_text = potential_display

        node = docutils.nodes.literal(rawtext, display_text)
        return [node], []

    sphinx_roles = [
        'func', 'function',
        'meth', 'method',
        'class',
        'mod', 'module',
        'attr', 'attribute',
        'obj', 'object',
        'data',
        'const', 'constant',
        'exc', 'exception',
        'var', 'variable',
        'type',
        'py:func', 'py:meth', 'py:class', 'py:mod', 'py:attr',
        'py:obj', 'py:data', 'py:const', 'py:exc',
    ]

    for role in sphinx_roles:
        docutils.parsers.rst.roles.register_canonical_role(role, sphinx_role)
        # Also register in language module to avoid INFO messages
        if hasattr(docutils.parsers.rst.languages.en, 'roles'):
            docutils.parsers.rst.languages.en.roles[role] = role


# pylama:ignore=D,C0116
class RSTVisitor(docutils.nodes.SparseNodeVisitor):
    """A visitor that produces rich renderables"""

    def __init__(
        self,
        document: docutils.nodes.document,
        console: Console,
        code_theme: Union[str, SyntaxTheme] = "monokai",
        guess_lexer: Optional[bool] = True,
        default_lexer: Optional[str] = "python",
    ) -> None:
        super().__init__(document)
        self.console = console
        self.code_theme = code_theme
        self.renderables = []
        self.supercript = str.maketrans(
            "1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ=+-*/×÷",
            "¹²³⁴⁵⁶⁷⁸⁹⁰ᵃᵇᶜᵈᵉᶠᵍʰⁱʲᵏˡᵐⁿᵒᵖᑫʳˢᵗᵘᵛʷˣʸᶻᴬᴮᶜᴰᴱᶠᴳᴴᴵᴶᴷᴸᴹᴺᴼᴾQᴿˢᵀᵁⱽᵂˣʸᶻ⁼⁺⁻*/×÷",
        )
        self.subscript = str.maketrans(
            "1234567890abcdefghijklmnopqrstuvwxyz=+-*/×÷", "₁₂₃₄₅₆₇₈₉₀abcdₑfgₕᵢⱼₖₗₘₙₒₚqᵣₛₜᵤᵥwₓyz₌₊₋*/×÷"
        )
        self.errors = []
        self.footer = []
        self.guess_lexer = guess_lexer
        self.default_lexer = default_lexer
        self.refname_to_renderable = {}

    def _find_lexer(self, node):
        lexer = (
            node["classes"][1] if len(node.get("classes")) >= 2 else (node["format"] if node.get("format") else None)
        )
        if lexer is None and self.guess_lexer:
            try:
                lexer = guess_lexer(node.astext())
            except ClassNotFound:
                lexer = self.default_lexer
            else:
                lexer = lexer.aliases[0] if lexer.aliases else self.default_lexer
            if lexer == "text":
                return self.default_lexer
            return lexer
        elif lexer is None and not self.guess_lexer:
            lexer = self.default_lexer
            return lexer
        return lexer

    def visit_reference(self, node):
        refuri = node.attributes.get("refuri")
        style = self.console.get_style("restructuredtext.reference", default="blue underline on default")
        if refuri:
            style = style.update_link(refuri)
        renderable = Text(node.astext().replace("\n", " "), style=style, end="")
        if self.renderables and isinstance(self.renderables[-1], Text):
            renderable.end = " "
            start = len(self.renderables[-1])
            self.renderables[-1].append_text(renderable)
        else:
            start = 0
            self.renderables.append(renderable)
        end = len(self.renderables[-1])

        if not refuri:
            # We'll get the URL reference later in visit_target.
            refname = node.attributes.get("refname")
            if refname:
                self.refname_to_renderable[refname] = (self.renderables[-1], start, end)
        raise docutils.nodes.SkipChildren()

    def visit_target(self, node):
        uri = node.get("refuri")
        if uri:
            for name in node["names"]:
                try:
                    renderable, start, end = self.refname_to_renderable[name]
                except KeyError:
                    continue
                style = renderable.get_style_at_offset(self.console, start)
                style = style.update_link(uri)
                renderable.stylize(style, start, end)
        raise docutils.nodes.SkipChildren()

    def visit_paragraph(self, node):
        if hasattr(node, "parent") and isinstance(node.parent, docutils.nodes.system_message):
            self.visit_system_message(node.parent)

    def depart_paragraph(self, node):  # pylint: disable=unused-argument
        if self.renderables and isinstance(self.renderables[-1], Text):
            if len(self.renderables[-1].end) == 0:
                self.renderables[-1].append("\n\n")

    def visit_title(self, node):
        style = self.console.get_style("restructuredtext.title", default="bold")
        self.renderables.append(Panel(Align(node.astext(), "center"), box=box.DOUBLE, style=style))
        raise docutils.nodes.SkipChildren()

    def visit_Text(self, node):
        style = self.console.get_style("restructuredtext.text", default="default on default not underline")
        if self.renderables and isinstance(self.renderables[-1], Text):
            self.renderables[-1].append_text(Text(node.astext().replace("\n", " "), style=style, end=" "))
            return
        self.renderables.append(Text(node.astext().replace("\n", " "), end="", style=style))

    def visit_comment(self, node):
        raise docutils.nodes.SkipChildren()

    def visit_admonition(self, node):
        style = self.console.get_style("restructuredtext.admonition", default="bold white")
        self.renderables.append(Panel(node.astext().replace("\n", " "), title="Admonition: ", style=style, border_style=style))
        raise docutils.nodes.SkipChildren()

    def visit_attention(self, node):
        style = self.console.get_style("restructuredtext.attention", default="bold black on yellow")
        self.renderables.append(Panel(node.astext().replace("\n", " "), title="Attention: ", style=style, border_style=style))
        raise docutils.nodes.SkipChildren()

    def visit_caution(self, node):
        style = self.console.get_style("restructuredtext.caution", default="red")
        self.renderables.append(Panel(node.astext().replace("\n", " "), title="Caution: ", style=style, border_style=style))
        raise docutils.nodes.SkipChildren()

    def visit_danger(self, node):
        style = self.console.get_style("restructuredtext.danger", default="bold white on red")
        self.renderables.append(Panel(node.astext().replace("\n", " "), title="DANGER: ", style=style, border_style=style))
        raise docutils.nodes.SkipChildren()

    def visit_error(self, node):
        style = self.console.get_style("restructuredtext.error", default="bold red")
        self.renderables.append(Panel(node.astext().replace("\n", " "), title="ERROR: ", style=style, border_style=style))
        raise docutils.nodes.SkipChildren()

    def visit_hint(self, node):
        style = self.console.get_style("restructuredtext.hint", default="yellow")
        self.renderables.append(Panel(node.astext().replace("\n", " "), title="Hint: ", style=style, border_style=style))
        raise docutils.nodes.SkipChildren()

    def visit_important(self, node):
        style = self.console.get_style("restructuredtext.important", default="bold blue")
        self.renderables.append(Panel(node.astext().replace("\n", " "), title="IMPORTANT: ", style=style, border_style=style))
        raise docutils.nodes.SkipChildren()

    def visit_note(self, node):
        style = self.console.get_style("restructuredtext.note", default="bold white")
        self.renderables.append(Panel(node.astext().replace("\n", " "), title="Note: ", style=style, border_style=style))
        raise docutils.nodes.SkipChildren()

    def visit_tip(self, node):
        style = self.console.get_style("restructuredtext.tip", default="bold green")
        self.renderables.append(Panel(node.astext().replace("\n", " "), title="Tip: ", style=style, border_style=style))
        raise docutils.nodes.SkipChildren()

    def visit_warning(self, node):
        style = self.console.get_style("restructuredtext.warning", default="bold yellow")
        self.renderables.append(Panel(node.astext().replace("\n", " "), title="Warning: ", style=style, border_style=style))
        raise docutils.nodes.SkipChildren()

    def visit_subscript(self, node):
        style = self.console.get_style("restructuredtext.subscript", default="none")
        if self.renderables and isinstance(self.renderables[-1], Text):
            self.renderables[-1].append_text(Text(node.astext().translate(self.subscript), style=style, end=" "))
            raise docutils.nodes.SkipChildren()
        self.renderables.append(Text(node.astext().translate(self.subscript), end="", style=style))
        raise docutils.nodes.SkipChildren()

    def visit_superscript(self, node):
        style = self.console.get_style("restructuredtext.superscript", default="none")
        if self.renderables and isinstance(self.renderables[-1], Text):
            self.renderables[-1].append_text(Text(node.astext().translate(self.supercript), style=style, end=" "))
            raise docutils.nodes.SkipChildren()
        self.renderables.append(Text(node.astext().translate(self.supercript), end="", style=style))
        raise docutils.nodes.SkipChildren()

    def visit_emphasis(self, node):
        style = self.console.get_style("restructuredtext.emphasis", default="italic")
        if self.renderables and isinstance(self.renderables[-1], Text):
            self.renderables[-1].append_text(Text(node.astext().replace("\n", " "), style=style, end=" "))
            raise docutils.nodes.SkipChildren()
        self.renderables.append(Text(node.astext().replace("\n", " "), style=style, end=""))
        raise docutils.nodes.SkipChildren()

    def visit_strong(self, node):
        style = self.console.get_style("restructuredtext.strong", default="bold")
        if self.renderables and isinstance(self.renderables[-1], Text):
            self.renderables[-1].append_text(Text(node.astext().replace("\n", " "), style=style, end=" "))
            raise docutils.nodes.SkipChildren()
        self.renderables.append(Text(node.astext().replace("\n", " "), style=style, end=""))
        raise docutils.nodes.SkipChildren()

    def visit_image(self, node):
        alt, target = None, None
        if ":target:" in node.rawsource:
            target = node.rawsource.split(":target:")[-1].strip()
        if ":alt:" in node.rawsource:
            alt = node.rawsource.split(":alt:")[-1].strip()
        self.renderables.append(
            Text("🌆 ")
            + Text(
                node.get("alt", alt or "Image"),
                style=Style(
                    link=node.get("target", target or "Image") or node.get("uri"),
                    color="#6088ff",
                ),
            )
        )
        raise docutils.nodes.SkipChildren()

    def visit_bullet_list(self, node):
        # Currently as it stands, this isn't gonna work with more than 3 nested levels
        # TODO: I need to figure out some way to handle nested lists recursively
        marker_style = self.console.get_style("restructuredtext.bullet_list_marker", default="bold yellow")
        text_style = self.console.get_style("restructuredtext.bullet_list_text", default="none")
        for list_item in node.children:
            nested_list = [i for i in list_item.children if isinstance(i, docutils.nodes.bullet_list)]
            if nested_list:
                for list_item in list_item.children:
                    self.renderables.append(Text("  ", end="") + Text(" ∘ ", end="", style=marker_style))
                    self.renderables.append(Text(list_item.astext().replace("\n", " "), style=text_style))
                    if isinstance(list_item, docutils.nodes.bullet_list):
                        for list_item in list_item.children:
                            self.renderables.append(Text("    ", end="") + Text(" ▪ ", end="", style=marker_style))
                            self.renderables.append(Text(list_item.astext().replace("\n", " "), style=text_style))
            self.renderables.append(Text(" • ", end="", style=marker_style))
            self.renderables.append(Text(list_item.astext().replace("\n", " "), style=text_style))
        self.renderables.append(NewLine())
        raise docutils.nodes.SkipChildren()

    def visit_enumerated_list(self, node):
        marker_style = self.console.get_style("restructuredtext.enumerated_list_marker", default="bold yellow")
        text_style = self.console.get_style("restructuredtext.enumerated_text", default="none")
        for i, list_item in enumerate(node.children, 1):
            self.renderables.append(Text(f" {i}", end=" ", style=marker_style))
            self.renderables.append(Text(list_item.astext().replace("\n", " "), style=text_style))

        self.renderables.append(NewLine())
        raise docutils.nodes.SkipChildren()

    def visit_literal(self, node):
        style = self.console.get_style("restructuredtext.inline_codeblock", default="grey78 on grey7")
        if self.renderables and isinstance(self.renderables[-1], Text):
            self.renderables[-1].append_text(Text(node.astext().replace("\n", " "), style=style, end=" "))
            raise docutils.nodes.SkipChildren()
        self.renderables.append(Text(node.astext().replace("\n", " "), style=style, end=""))
        raise docutils.nodes.SkipChildren()

    def visit_literal_block(self, node):
        style = self.console.get_style("restructuredtext.literal_block_border", default="grey58")
        if self.renderables and isinstance(self.renderables[-1], Text):
            self.renderables[-1].rstrip()
            self.renderables[-1].append_text(Text("\n"))
        lexer = self._find_lexer(node)
        self.renderables.append(
            Panel(Syntax(node.astext(), lexer, theme=self.code_theme), border_style=style, box=box.SQUARE, title=lexer)
        )
        raise docutils.nodes.SkipChildren()

    def visit_system_message(self, node):
        self.errors.append(
            Panel(
                self.console.render_str(node.astext()),
                title=f"System Message: {node.attributes.get('type', '?')}/{node.attributes.get('level', '?')} ({node.attributes.get('source', '?')}, line {node.attributes.get('line', '?')});",
                border_style={None: "none", "INFO": "bold cyan", "WARNING": "bold yellow", "ERROR": "bold red"}[
                    node.attributes.get("type")
                ],
            ),
        )
        raise docutils.nodes.SkipChildren()

    def visit_field(self, node):
        field_name_style = self.console.get_style("restructuredtext.field_name", default="bold")
        field_value_style = self.console.get_style("restructuredtext.field_value", default="none")
        previous_table = None
        if isinstance(self.renderables[-1], Table):
            possible_table = self.renderables[-1]
            if (possible_table.columns[0].header == "Field Name") and (possible_table.columns[1].header == "Field Value"):
                table = possible_table
                previous_table = True
            else:
                table = Table("Field Name", "Field Value", show_lines=True)
                previous_table = False
        else:
            previous_table = False
        if previous_table is False:
            table = Table("Field Name", "Field Value", show_lines=True)
            table.add_row(Text(node.children[0].astext(), style=field_name_style), Text(node.children[1].astext(), style=field_value_style))
            self.renderables.append(table)
        else:
            table.add_row(Text(node.children[0].astext(), style=field_name_style), Text(node.children[1].astext(), style=field_value_style))
        raise docutils.nodes.SkipChildren()

    def visit_definition_list(self, node):
        term_style = self.console.get_style("restructuredtext.term_style", default="none")
        classifier_style = self.console.get_style("restructuredtext.classifier_style", default="cyan")
        definitions_style = self.console.get_style("restructuredtext.definitions_style", default="none")
        for child in node.children:
            try:
                term, classifier, definitions = child.children
            except ValueError:
                term, classifier = child.children[0], child.children[1]
                if len(child.children) > 2:
                    for children in child.children[2:]:
                        if isinstance(children, docutils.nodes.bullet_list):
                            self.visit_bullet_list(children)
                        elif isinstance(children, docutils.nodes.literal_block):
                            self.visit_literal_block(children)
                        elif isinstance(children, docutils.nodes.literal):
                            self.visit_literal(children)
                        elif isinstance(children, docutils.nodes.block_quote):
                            self.visit_block_quote(children)
                else:

                    self.renderables.append(
                        Text.from_markup(f"[{classifier_style}]{term.astext()}[/{classifier_style}]")
                        + Text("\n    ", end="")
                        + Text(classifier.astext().replace("\n", " "), style=definitions_style)
                        + Text("\n      ", end="")
                    )
            else:
                self.renderables.append(
                    Text("    ")
                    + Text(term.astext(), style=term_style, end="")
                    + Text(" : ", end="")
                    + Text(classifier.astext(), style=classifier_style)
                    + Text("\n      ", end="")
                    + Text(definitions.astext().replace("\n", " "), style=definitions_style)
                    + Text("\n", end="")
                )
        raise docutils.nodes.SkipChildren()

    def visit_option_list(self, node):
        option_string_style = self.console.get_style("restructuredtext.option_string", default="none")
        option_argument_style = self.console.get_style("restructuredtext.option_argument", default="none")
        option_child_text_separator_style = self.console.get_style(
            "restructuredtext.option_child_text_separator", default="none"
        )
        option_description_style = self.console.get_style("restructuredtext.option_description", default="none")
        for option_list_item in node.children:
            option_group, description = option_list_item.children
            # option_group.child_text_separator.join(map(lambda x: x.astext(), option_group.children)))
            option_text = Text(end="")
            for option in option_group.children:
                try:
                    option_string, option_argument = option.children
                except ValueError:
                    option_string, option_argument = option.children[0], None
                option_text += (
                    Text(option_string.astext(), style=option_string_style)
                    + (Text(option_argument.astext(), style=option_argument_style) if option_argument else Text())
                    + (
                        Text(option_group.child_text_separator, style=option_child_text_separator_style)
                        if len(option_group.children) > 1
                        else ""
                    )
                )
            if description:
                option_text += Text("\n    ")
                option_text += Text(description.astext(), style=option_description_style)
            self.renderables.append(option_text + Text("\n"))
        raise docutils.nodes.SkipChildren()

    def visit_doctest_block(self, node):
        style = self.console.get_style("restructuredtext.literal_block_border", default="grey58")
        self.renderables.append(
            Panel(
                Syntax(node.astext(), "pycon", theme=self.code_theme),
                border_style=style,
                box=box.SQUARE,
            )
        )
        raise docutils.nodes.SkipChildren()

    def visit_block_quote(self, node):
        text_style = self.console.get_style("restructuredtext.blockquote_text", default="white")
        marker_style = self.console.get_style(
            "restructuredtext.blockquote_attribution_marker", default="bright_magenta"
        )
        author_style = self.console.get_style("restructuredtext.blockquote_attribution_text", default="grey89")
        try:
            paragraph, attribution = node.children
        except ValueError:
            paragraph = node.children[0]
            self.renderables.append(
                Text("    ")
                + Text(paragraph.astext().replace('\n', ' '), style=text_style)
                + Text("\n\n")
            )
        else:
            self.renderables.append(
                Text("▌ ", style=marker_style)
                + Text(paragraph.astext(), style=text_style)
                + Text("\n")
                + Text("  - " + attribution.astext(), style=author_style)
            )
        raise docutils.nodes.SkipChildren()

    def visit_line_block(self, node):
        for line in node.children:
            self.renderables.append(Text(line.astext()))
        raise docutils.nodes.SkipChildren()

    def visit_sidebar(self, node):
        if len(node.children) > 2:
            title, subtitle, paragraph = node.children
        else:
            title, subtitle, paragraph = node.children[0], "", node.children[1]

        self.renderables.append(
            Panel(paragraph.astext(), title=title.astext(), subtitle=subtitle.astext(), expand=False)
        )

        raise docutils.nodes.SkipChildren()

    def visit_transition(self, node):
        style = self.console.get_style("restructuredtext.hr", default="yellow")
        self.renderables.append(Rule(style=style))

    def visit_rubric(self, node):
        self.visit_title(node)

    def visit_math_block(self, node):
        if self.renderables and isinstance(self.renderables[-1], Text):
            self.renderables[-1].append(Text(node.astext(), end=" "))
            raise docutils.nodes.SkipChildren()
        self.renderables.append(Text(node.astext()))
        raise docutils.nodes.SkipChildren()

    def visit_citation(self, node):
        border_style = self.console.get_style("restructuredtext.citation_border", default="grey74")
        self.renderables.append(Panel(node.astext(), title="citation", border_style=border_style))
        raise docutils.nodes.SkipChildren()

    def visit_citation_reference(self, node):
        style = self.console.get_style("restructuredtext.citation_reference", default="grey74")
        if self.renderables and isinstance(self.renderables[-1], Text):
            self.renderables[-1].append(node.astext().replace("\n", " "), style=style)
            raise docutils.nodes.SkipChildren()
        self.renderables.append(Text(node.astext().replace("\n", " "), style=style, end=""))
        raise docutils.nodes.SkipChildren()

    def visit_header(self, node):
        style = self.console.get_style("restructuredtext.caption", default="bold")
        self.renderables.insert(0, Panel(Align(node.astext(), "center"), title="caption", box=box.DOUBLE, style=style))
        raise docutils.nodes.SkipChildren()

    def visit_footer(self, node):
        self.footer.append(Align(node.astext(), "center"))
        raise docutils.nodes.SkipChildren()

    def visit_footnote(self, node):
        self.footer.append(Align(node.astext(), "center"))
        raise docutils.nodes.SkipChildren()

    def visit_generated(self, node):
        self.footer.append(Align(node.astext(), "center"))
        raise docutils.nodes.SkipChildren()

    def visit_pendings(self, node):
        raise docutils.nodes.SkipChildren()

    def visit_problematic(self, node):
        self.errors.append(
            Panel(
                Syntax(node.astext(), lexer="rst", theme=self.code_theme),
                title=f"System Message: Problematic Element",
                border_style="bold red",
            ),
        )

    def visit_raw(self, node):
        style = self.console.get_style("restructuredtext.literal_block_border", default="grey58")
        lexer = self._find_lexer(node)
        text = node.astext()
        title = "raw " + ("stripped raw html" if lexer == "html" else lexer)

        if lexer == "html":
            text = strip_tags(text)
            lexer = guess_lexer(text).aliases[0] if self.guess_lexer else self.default_lexer

        self.renderables.append(
            Panel(Syntax(text, lexer, theme=self.code_theme), border_style=style, box=box.SQUARE, title=title)
        )
        raise docutils.nodes.SkipChildren()


class RestructuredText(JupyterMixin):
    """A reStructuredText renderable for rich.

    Parameters
    ----------
    markup : str
        A string containing reStructuredText markup.
    code_theme : Optional[Union[str, SyntaxTheme]]
        Pygments theme for code blocks. Defaults to "monokai".
    show_errors : Optional[bool]
        Whether to show system_messages aka errors and warnings.
    guess_lexer : Optional[bool]
        Whether to guess lexers for code blocks without specified language.
    default_lexer : Optional[str]
        Which lexer to use if no lexer is guessed or found. Defaults to "python"
    sphinx_compat : Optional[bool]
        Enable compatibility with Sphinx roles (func, meth, class, etc.) commonly used in
        Python docstrings. When enabled, these roles render as inline code instead of errors.
        Defaults to True for better compatibility with Python documentation.
    filename : Optional[str]
        A file name to use for error messages, useful for debugging purposes. Defaults to "<rst-document>"
    """

    def __init__(
        self,
        markup: str,
        code_theme: Optional[Union[str, SyntaxTheme]] = "monokai",
        show_errors: Optional[bool] = True,
        guess_lexer: Optional[bool] = False,
        default_lexer: Optional[str] = "python",
        sphinx_compat: Optional[bool] = True,
        filename: Optional[str] = "<rst-document>"
    ) -> None:
        self.markup = markup
        self.code_theme = code_theme
        self.log_errors = show_errors
        self.guess_lexer = guess_lexer
        self.default_lexer = default_lexer
        self.sphinx_compat = sphinx_compat
        self.filename = filename

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        if self.sphinx_compat:
            _register_sphinx_roles()

        # Docutils version compatability; from https://stackoverflow.com/a/75996218
        if hasattr(docutils.frontend, 'get_default_settings'):
            # docutils >= 0.18
            settings = docutils.frontend.get_default_settings(docutils.parsers.rst.Parser)
        else:
            # docutils < 0.18
            settings = docutils.frontend.OptionParser(components=(docutils.parsers.rst.Parser,)).get_default_values()
        settings.report_level = 69
        source = docutils.io.StringInput(self.markup)
        document = docutils.utils.new_document(self.filename, settings)
        rst_parser = docutils.parsers.rst.Parser()
        rst_parser.parse(source.read(), document)

        # Render the RST `document` using Rich.
        visitor = RSTVisitor(
            document,
            console=console,
            code_theme=self.code_theme,
            guess_lexer=self.guess_lexer,
            default_lexer=self.default_lexer,
        )
        document.walkabout(visitor)

        # Strip all trailing newlines and newline-like rich objects
        while visitor.renderables:
            if isinstance(visitor.renderables[-1], Text):
                visitor.renderables[-1].rstrip()
                visitor.renderables[-1].end = "\n"
                if visitor.renderables[-1]:  # The Text object still contains data.
                    break
                else:
                    visitor.renderables.pop()
            elif isinstance(visitor.renderables[-1], NewLine):
                visitor.renderables.pop()
            else:
                break

        for renderable in visitor.renderables:
            yield from console.render(renderable, options)
        if self.log_errors and visitor.errors:
            for error in visitor.errors:
                yield from console.render(error, options)
        style = console.get_style("restructuredtext.footer", default="none")
        border_style = console.get_style("restructuredtext.footer_border", default="grey74")
        footer_text = ""
        for element in visitor.footer:
            footer_text = element
        if footer_text:
            yield from console.render(
                Panel(footer_text, title="Footer", box=box.SQUARE, border_style=border_style, style=style)
            )


RST = reST = ReStructuredText = reStructuredText = RestructuredText
