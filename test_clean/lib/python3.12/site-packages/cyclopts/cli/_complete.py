"""Hidden completion helper command for dynamic shell completion."""

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from cyclopts.cli import app
from cyclopts.loader import load_app_from_script
from cyclopts.parameter import Parameter

if TYPE_CHECKING:
    from cyclopts import App

MAX_DESCRIPTION_LENGTH = 60


def _extract_short_description(help_text: str) -> str:
    """Extract first line of help text as a short description.

    Parameters
    ----------
    help_text : str
        Full help text to extract from.

    Returns
    -------
    str
        First line of help text, or empty string if parsing fails.
    """
    from cyclopts.help.help import docstring_parse

    try:
        parsed = docstring_parse(help_text, "plaintext")
        return parsed.short_description or ""
    except Exception:
        return str(help_text).split("\n")[0]


def _print_subcommand_completions(app_obj: "App") -> None:
    """Print completions for subcommands of the given app.

    Parameters
    ----------
    app_obj : App
        Application object to extract subcommands from.
    """
    from cyclopts.group_extractors import groups_from_app

    for _, registered_commands in groups_from_app(app_obj):
        for registered_command in registered_commands:
            if registered_command.app.show:
                for name in registered_command.names:
                    if not name.startswith("-"):
                        short_desc = ""
                        if registered_command.app.help:
                            short_desc = _extract_short_description(registered_command.app.help)

                        if short_desc:
                            print(f"{name}:{short_desc}")
                        else:
                            print(name)


def _print_option_completions(app_obj: "App") -> None:
    """Print completions for options of the given app's default command.

    Parameters
    ----------
    app_obj : App
        Application object to extract options from.
    """
    if not app_obj.default_command:
        return

    try:
        arguments = app_obj.assemble_argument_collection(parse_docstring=True)
        for argument in arguments:
            if not argument.is_positional_only() and argument.show:
                for name in argument.names:
                    if name.startswith("-"):
                        desc = argument.parameter.help or ""
                        desc = desc.split("\n")[0][:MAX_DESCRIPTION_LENGTH]
                        if desc:
                            print(f"{name}:{desc}")
                        else:
                            print(name)
    except Exception:
        pass


@app.command(name="_complete", show=False)
def complete(
    subcommand: Annotated[str, Parameter(allow_leading_hyphen=True)],
    script: Annotated[Path, Parameter(allow_leading_hyphen=True)],
    *words: Annotated[str, Parameter(allow_leading_hyphen=True)],
) -> None:
    """Internal completion helper (hidden from users).

    This command is called by the shell completion system to dynamically
    generate completions for the 'run' command by loading the target script
    and extracting its available commands and options.

    Parameters
    ----------
    subcommand : str
        The cyclopts subcommand being completed (e.g., "run").
    script : Path
        Python script path to load for completion extraction.
    words : str
        Current command line words for context-aware completion.
    """
    if subcommand != "run":
        return

    try:
        app_obj, _ = load_app_from_script(script)
    except (ImportError, SyntaxError, AttributeError, FileNotFoundError):
        return

    words_list = list(words) if words else []

    # Complete from root app if no words or only empty string (initial completion)
    if not words_list or (len(words_list) == 1 and not words_list[0]):
        _print_subcommand_completions(app_obj)
        _print_option_completions(app_obj)
    else:
        try:
            _, execution_path, _ = app_obj.parse_commands(words_list)
            current_app = execution_path[-1]
            _print_subcommand_completions(current_app)
            _print_option_completions(current_app)
        except Exception:
            pass
