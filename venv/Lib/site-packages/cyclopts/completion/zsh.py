"""Zsh completion script generator.

Generates static zsh completion scripts using the compsys framework.
No runtime Python dependency.
"""

import re
from textwrap import dedent
from textwrap import indent as textwrap_indent
from typing import TYPE_CHECKING

from cyclopts.completion._base import (
    CompletionAction,
    CompletionData,
    clean_choice_text,
    escape_for_shell_pattern,
    extract_completion_data,
    get_completion_action,
    strip_markup,
)
from cyclopts.help.help import docstring_parse

if TYPE_CHECKING:
    from cyclopts import App
    from cyclopts.argument import Argument, ArgumentCollection


def generate_completion_script(app: "App", prog_name: str) -> str:
    """Generate zsh completion script.

    Parameters
    ----------
    app : App
        The Cyclopts application to generate completion for.
    prog_name : str
        Program name (alphanumeric with hyphens/underscores).

    Returns
    -------
    str
        Complete zsh completion script.

    Raises
    ------
    ValueError
        If prog_name contains invalid characters.
    """
    if not prog_name or not re.match(r"^[a-zA-Z0-9_-]+$", prog_name):
        raise ValueError(f"Invalid prog_name: {prog_name!r}. Must be alphanumeric with hyphens/underscores.")

    completion_data = extract_completion_data(app)

    lines = [
        f"#compdef {prog_name}",
        "",
        f"_{prog_name}() {{",
        "  local line state",
        "",
    ]

    lines.extend(
        _generate_completion_for_path(
            completion_data,
            (),
            prog_name=prog_name,
            help_flags=tuple(app.help_flags) if app.help_flags else (),
            version_flags=tuple(app.version_flags) if app.version_flags else (),
        )
    )

    lines.extend(
        [
            "}",
            "",
        ]
    )

    return "\n".join(lines) + "\n"


def _generate_run_command_completion(
    arguments: "ArgumentCollection",
    indent_str: str,
    prog_name: str,
) -> list[str]:
    """Generate dynamic completion for the 'run' command.

    Parameters
    ----------
    arguments : ArgumentCollection
        Arguments for run command.
    indent_str : str
        Indentation string.
    prog_name : str
        Program name.

    Returns
    -------
    list[str]
        Zsh completion code lines.
    """
    template = dedent(f"""\
        local script_path
        local -a completions
        local -a remaining_words

        # If completing first argument (the script path), suggest files
        if [[ $CURRENT -eq 2 ]]; then
          _files
          return
        fi

        # Get absolute path to the script file
        script_path=${{words[2]}}
        script_path=${{script_path:a}}
        if [[ -f $script_path ]]; then
          remaining_words=(${{words[3,-1]}})
          local result
          local cmd

          if command -v {prog_name} &>/dev/null; then
            cmd="{prog_name}"
          else
            return
          fi
          # Call back into cyclopts to get dynamic completions from the script
          result=$($cmd _complete run "$script_path" "${{remaining_words[@]}}" 2>/dev/null)
          if [[ -n $result ]]; then
            # Parse and display completion results
            completions=()
            while IFS= read -r line; do
              completions+=($line)
            done <<< $result
            _describe 'command' completions
          fi
        fi""")

    indented = textwrap_indent(template, indent_str)
    return [line.rstrip() for line in indented.split("\n")]


def _generate_nested_positional_specs(
    positional_args: list["Argument"],
    help_format: str,
) -> list[str]:
    """Generate positional argument specs for nested command context.

    In nested contexts (after *::arg:->args), word indexing is shifted:
    - words[1] = subcommand name
    - words[2] = first positional argument
    - words[3] = second positional argument, etc.

    Parameters
    ----------
    positional_args : list[Argument]
        Positional arguments to generate specs for.
    help_format : str
        Help text format.

    Returns
    -------
    list[str]
        List of zsh positional argument specs.
    """
    specs = []

    # Check if we have variadic positionals
    variadic_args = [arg for arg in positional_args if arg.is_var_positional()]
    non_variadic_args = [arg for arg in positional_args if not arg.is_var_positional()]

    # Generate specs for non-variadic positionals
    for arg in non_variadic_args:
        # Position in nested context: After *::arg:->args, $words[1] is the subcommand
        # So positionals start at position 1 (not 2)
        # Use 1-based indexing: first positional is '1:', second is '2:', etc.
        pos = 1 + (arg.index or 0)
        desc = _get_description_from_argument(arg, help_format)

        # Check for choices first (Literal/Enum types)
        choices = arg.get_choices(force=True)
        if choices:
            escaped_choices = [_escape_completion_choice(clean_choice_text(c)) for c in choices]
            choices_str = " ".join(escaped_choices)
            action = f"({choices_str})"
        else:
            action = _map_completion_action_to_zsh(get_completion_action(arg.hint))

        spec = f"'{pos}:{desc}:{action}'" if action else f"'{pos}:{desc}'"
        specs.append(spec)

    # Generate specs for variadic positionals
    for arg in variadic_args:
        desc = _get_description_from_argument(arg, help_format)

        choices = arg.get_choices(force=True)
        if choices:
            escaped_choices = [_escape_completion_choice(clean_choice_text(c)) for c in choices]
            choices_str = " ".join(escaped_choices)
            action = f"({choices_str})"
        else:
            action = _map_completion_action_to_zsh(get_completion_action(arg.hint))

        spec = f"'*:{desc}:{action}'" if action else f"'*:{desc}'"
        specs.append(spec)

    return specs


def _generate_describe_completion(
    argument: "Argument",
    help_format: str,
    indent_str: str,
) -> list[str]:
    """Generate _describe-based completion for a single positional argument.

    Parameters
    ----------
    argument : Argument
        Argument to generate completion for.
    help_format : str
        Help text format.
    indent_str : str
        Indentation string.

    Returns
    -------
    list[str]
        Zsh completion code lines.
    """
    lines = []
    desc = _get_description_from_argument(argument, help_format)

    # Check for choices (Literal/Enum types)
    choices = argument.get_choices(force=True)
    if choices:
        # Generate choices array with descriptions
        escaped_choices = [_escape_completion_choice(clean_choice_text(c)) for c in choices]
        lines.append(f"{indent_str}local -a choices")
        lines.append(f"{indent_str}choices=(")
        for choice in escaped_choices:
            lines.append(f"{indent_str}  '{choice}:{desc}'")
        lines.append(f"{indent_str})")
        lines.append(f"{indent_str}_describe 'argument' choices")
    else:
        # Use completion action (files, directories, or nothing)
        action = get_completion_action(argument.hint)
        if action == CompletionAction.FILES:
            lines.append(f"{indent_str}_files")
        elif action == CompletionAction.DIRECTORIES:
            lines.append(f"{indent_str}_directories")
        # For other types, provide no completion

    return lines


def _generate_completion_for_path(
    completion_data: dict[tuple[str, ...], CompletionData],
    command_path: tuple[str, ...],
    indent: int = 2,
    prog_name: str = "cyclopts",
    help_flags: tuple[str, ...] = (),
    version_flags: tuple[str, ...] = (),
) -> list[str]:
    """Generate completion code for a specific command path.

    Parameters
    ----------
    completion_data : dict
        Extracted completion data.
    command_path : tuple[str, ...]
        Command path.
    indent : int
        Indentation level.
    prog_name : str
        Program name.
    help_flags : tuple[str, ...]
        Help flags.
    version_flags : tuple[str, ...]
        Version flags.

    Returns
    -------
    list[str]
        Zsh code lines.
    """
    data = completion_data[command_path]
    commands = data.commands
    arguments = data.arguments
    indent_str = " " * indent
    lines = []

    if command_path == ("run",) and prog_name == "cyclopts":
        lines.extend(_generate_run_command_completion(arguments, indent_str, prog_name))
        return lines

    args_specs = []
    positional_specs = []

    # Separate positional from keyword arguments
    # Include all arguments with an index (both positional-only and positional-or-keyword)
    positional_args = [arg for arg in arguments if arg.index is not None and arg.show]
    keyword_args = [arg for arg in arguments if not arg.is_positional_only() and arg.show]

    # Sort positionals by index (should never be None for positional-only args)
    positional_args.sort(key=lambda a: a.index or 0)

    # Generate keyword argument specs
    for argument in keyword_args:
        specs = _generate_keyword_specs(argument, data.help_format)
        args_specs.extend(specs)

    # Check for flag commands (commands that look like options)
    flag_command_names = set()
    for registered_command in commands:
        if any(name.startswith("-") for name in registered_command.names):
            specs = _generate_keyword_specs_for_command(
                registered_command.names, registered_command.app, data.help_format
            )
            args_specs.extend(specs)
            flag_command_names.update(registered_command.names)

    # Add help and version flags to all command paths (if not already added as flag commands)
    for flag in help_flags:
        if flag.startswith("-") and flag not in flag_command_names:
            spec = f"'{flag}[Display this message and exit.]'"
            args_specs.append(spec)

    for flag in version_flags:
        if flag.startswith("-") and flag not in flag_command_names:
            spec = f"'{flag}[Display application version.]'"
            args_specs.append(spec)

    has_non_flag_commands = any(
        not cmd_name.startswith("-") for registered_command in commands for cmd_name in registered_command.names
    )

    # Generate positional argument specs
    # Only add positionals if there are no subcommands (they conflict in zsh)
    if positional_args and not has_non_flag_commands:
        if command_path:
            # Nested context: use shifted positional indexing (words[1] is subcommand)
            positional_specs = _generate_nested_positional_specs(positional_args, data.help_format)
        else:
            # Root context: standard _arguments works fine
            for argument in positional_args:
                spec = _generate_positional_spec(argument, data.help_format)
                positional_specs.append(spec)

        # Add positionals BEFORE options to prioritize them in completion
        args_specs = positional_specs + args_specs

    if has_non_flag_commands:
        args_specs.append("'1: :->cmds'")
        args_specs.append("'*::arg:->args'")

    if args_specs:
        c_flag = "-C " if has_non_flag_commands else ""
        lines.append(f"{indent_str}_arguments {c_flag}\\")
        for spec in args_specs[:-1]:
            lines.append(f"{indent_str}  {spec} \\")
        lines.append(f"{indent_str}  {args_specs[-1]}")
        lines.append("")

    if has_non_flag_commands:
        lines.append(f"{indent_str}case $state in")
        lines.append(f"{indent_str}  cmds)")

        cmd_list = []
        for registered_command in commands:
            for cmd_name in registered_command.names:
                if not cmd_name.startswith("-"):
                    desc = _safe_get_description_from_app(registered_command.app, data.help_format)
                    escaped_cmd_name = _escape_completion_choice(cmd_name)
                    cmd_list.append(f"'{escaped_cmd_name}:{desc}'")

        lines.append(f"{indent_str}    local -a commands")
        lines.append(f"{indent_str}    commands=(")
        for cmd in cmd_list:
            lines.append(f"{indent_str}      {cmd}")
        lines.append(f"{indent_str}    )")
        lines.append(f"{indent_str}    _describe -t commands 'command' commands")
        lines.append(f"{indent_str}    ;;")

        lines.append(f"{indent_str}  args)")
        lines.append(f"{indent_str}    case $words[1] in")

        for registered_command in commands:
            for cmd_name in registered_command.names:
                if cmd_name.startswith("-"):
                    continue

                sub_path = command_path + (cmd_name,)
                if sub_path in completion_data:
                    escaped_case_name = _escape_command_name_for_case(cmd_name)
                    lines.append(f"{indent_str}      {escaped_case_name})")
                    sub_lines = _generate_completion_for_path(
                        completion_data, sub_path, indent + 8, prog_name, help_flags, version_flags
                    )
                    lines.extend(sub_lines)
                    lines.append(f"{indent_str}        ;;")

        lines.append(f"{indent_str}    esac")
        lines.append(f"{indent_str}    ;;")
        lines.append(f"{indent_str}esac")

    return lines


def _escape_completion_choice(choice: str) -> str:
    """Escape special characters in a completion choice value for zsh.

    Choice should already be cleaned via clean_choice_text() before calling this function.
    This function only applies zsh-specific escaping.

    Parameters
    ----------
    choice : str
        Cleaned choice value.

    Returns
    -------
    str
        Escaped choice value safe for zsh completion.
    """
    choice = choice.replace("\\", "\\\\")
    choice = choice.replace("'", r"'\''")
    choice = choice.replace("`", "\\`")
    choice = choice.replace("$", "\\$")
    choice = choice.replace('"', '\\"')
    choice = choice.replace(" ", "\\ ")
    choice = choice.replace("(", "\\(")
    choice = choice.replace(")", "\\)")
    choice = choice.replace("[", "\\[")
    choice = choice.replace("]", "\\]")
    choice = choice.replace(";", "\\;")
    choice = choice.replace("|", "\\|")
    choice = choice.replace("&", "\\&")
    choice = choice.replace(":", "\\:")
    return choice


def _escape_command_name_for_case(name: str) -> str:
    """Escape special characters in command name for zsh case patterns.

    In zsh case patterns, glob characters need to be escaped to match literally.
    Colons also need escaping because zsh's completion system may treat them
    specially when populating the $words array after _describe completion.

    Parameters
    ----------
    name : str
        Command name.

    Returns
    -------
    str
        Escaped command name safe for zsh case patterns.
    """
    # zsh case patterns have more special chars than bash: includes ()|
    # Colons (:) also need escaping for completion $words matching (issue #715)
    return escape_for_shell_pattern(name, chars="*?[]()|:")


def _escape_zsh_description(text: str) -> str:
    """Escape special characters in description text for zsh.

    Parameters
    ----------
    text : str
        Cleaned description text.

    Returns
    -------
    str
        Escaped description safe for zsh completion.
    """
    text = text.replace("\\", "\\\\")
    text = text.replace("`", "\\`")
    text = text.replace("$", "\\$")
    text = text.replace('"', '\\"')
    text = text.replace("'", r"'\''")
    text = text.replace(":", r"\:")
    text = text.replace("[", r"\[")
    text = text.replace("]", r"\]")
    return text


def _generate_keyword_specs(argument: "Argument", help_format: str) -> list[str]:
    """Generate zsh _arguments specs for a keyword argument.

    Parameters
    ----------
    argument : Argument
        Argument object from ArgumentCollection.
    help_format : str
        Help text format.

    Returns
    -------
    list[str]
        List of zsh argument specs.
    """
    specs = []
    desc = _get_description_from_argument(argument, help_format)

    flag = argument.is_flag()

    # Determine completion action
    action = ""
    choices = argument.get_choices(force=True)
    if choices:
        escaped_choices = [_escape_completion_choice(clean_choice_text(c)) for c in choices]
        choices_str = " ".join(escaped_choices)
        action = f"({choices_str})"
        flag = False
    else:
        action = _map_completion_action_to_zsh(get_completion_action(argument.hint))

    # Generate specs for positive names (from parameter.name)
    for name in argument.parameter.name:  # pyright: ignore[reportOptionalIterable]
        if not name.startswith("-"):
            continue
        if flag and not action:
            spec = f"'{name}[{desc}]'"
        elif action:
            spec = f"'{name}[{desc}]:{name.lstrip('-')}:{action}'"
        else:
            spec = f"'{name}[{desc}]:{name.lstrip('-')}'"
        specs.append(spec)

    # Generate specs for negative names (always flags, consume no tokens)
    for name in argument.negatives:
        if not name.startswith("-"):
            continue
        # Negative flags always consume zero tokens (e.g., --empty-items, --no-verbose)
        spec = f"'{name}[{desc}]'"
        specs.append(spec)

    return specs


def _generate_positional_spec(argument: "Argument", help_format: str) -> str:
    """Generate zsh _arguments spec for a positional argument.

    Parameters
    ----------
    argument : Argument
        Positional argument object.
    help_format : str
        Help text format.

    Returns
    -------
    str
        Zsh positional argument spec.
    """
    desc = _get_description_from_argument(argument, help_format)

    # Check for choices first (Literal/Enum types)
    choices = argument.get_choices(force=True)
    if choices:
        escaped_choices = [_escape_completion_choice(clean_choice_text(c)) for c in choices]
        choices_str = " ".join(escaped_choices)
        action = f"({choices_str})"
    else:
        action = _map_completion_action_to_zsh(get_completion_action(argument.hint))

    if argument.is_var_positional():
        # Variadic positional (*args)
        return f"'*:{desc}:{action}'" if action else f"'*:{desc}'"

    # Regular positional - zsh uses 1-based indexing
    if argument.index is None:
        raise ValueError(f"Positional-only argument {argument.names} missing index")
    pos = argument.index + 1
    return f"'{pos}:{desc}:{action}'" if action else f"'{pos}:{desc}'"


def _generate_keyword_specs_for_command(names: tuple[str, ...], cmd_app: "App", help_format: str) -> list[str]:
    """Generate zsh _arguments specs for a command that looks like a flag.

    Parameters
    ----------
    names : tuple[str, ...]
        Registered names for the command.
    cmd_app : App
        Command app with flag-like names.
    help_format : str
        Help text format.

    Returns
    -------
    list[str]
        List of zsh argument specs.
    """
    specs = []
    desc = _safe_get_description_from_app(cmd_app, help_format)

    for name in names:
        if name.startswith("-"):
            spec = f"'{name}[{desc}]'"
            specs.append(spec)

    return specs


def _map_completion_action_to_zsh(action: CompletionAction) -> str:
    """Map shell-agnostic completion action to zsh-specific completion command.

    Parameters
    ----------
    action : CompletionAction
        Shell-agnostic completion action.

    Returns
    -------
    str
        Zsh completion command (e.g., "_files", "_directories", or "").
    """
    if action == CompletionAction.FILES:
        return "_files"
    elif action == CompletionAction.DIRECTORIES:
        return "_directories"
    return ""


def _get_description_from_argument(argument: "Argument", help_format: str) -> str:
    """Extract plain text description from Argument, escaping zsh special chars.

    Parameters
    ----------
    argument : Argument
        Argument object with parameter help text.
    help_format : str
        Help text format.

    Returns
    -------
    str
        Escaped plain text description (truncated to 80 chars).
        Falls back to argument name if help text is empty, since zsh _arguments
        requires a non-empty description for positional specs to work correctly.
    """
    text = strip_markup(argument.parameter.help or "", format=help_format)
    if not text:
        # Use primary argument name as fallback - zsh _arguments requires non-empty
        # description for positional specs to provide completions
        text = argument.names[0] if argument.names else "argument"
    return _escape_zsh_description(text)


def _safe_get_description_from_app(cmd_app: "App", help_format: str) -> str:
    """Extract plain text description from App, escaping zsh special chars.

    Parameters
    ----------
    cmd_app : App
        Command app with help text.
    help_format : str
        Help text format.

    Returns
    -------
    str
        Escaped plain text description (truncated to 80 chars).
    """
    if not cmd_app.help:
        return ""

    try:
        parsed = docstring_parse(cmd_app.help, "plaintext")
        text = parsed.short_description or ""
    except Exception:
        text = str(cmd_app.help)

    text = strip_markup(text, format=help_format)
    return _escape_zsh_description(text)
