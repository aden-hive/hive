"""Generate documentation for Cyclopts applications."""

from pathlib import Path
from typing import Annotated

from cyclopts.cli import app
from cyclopts.docs.types import (
    FORMAT_ALIASES,
    DocFormat,
    normalize_format,
)
from cyclopts.group import Group
from cyclopts.loader import load_app_from_script
from cyclopts.parameter import Parameter
from cyclopts.utils import UNSET


def _format_group_validator(argument_collection):
    format_arg = argument_collection.get("--format")
    output_arg = argument_collection.get("--output")

    if format_arg.value is UNSET:
        if output_arg.value is UNSET:
            raise ValueError('"--format" must be specified when output path is not provided.')

        if not output_arg.value or not hasattr(output_arg.value, "suffix"):
            raise ValueError('"--output" must be a valid file path when format is not specified.')

        suffix = output_arg.value.suffix.lower()

        if not suffix:
            raise ValueError(
                "Output file must have an extension to infer format (e.g., .md, .html, .rst). "
                'Please specify "--format" explicitly or add an extension to the output file.'
            )

        # Strip the leading period from suffix to look up in FORMAT_ALIASES
        suffix_key = suffix.lstrip(".")

        if not suffix_key:
            raise ValueError(
                "Invalid file extension. Output file must have a valid extension after the period. "
                'Please specify "--format" explicitly.'
            )

        inferred_format = FORMAT_ALIASES.get(suffix_key)

        if inferred_format is None:
            supported_extensions = [f".{ext}" for ext in FORMAT_ALIASES.keys() if len(ext) <= 4]
            raise ValueError(
                f'Cannot infer format from output extension "{suffix}". '
                f"Supported extensions: {', '.join(sorted(set(supported_extensions)))}. "
                f'Please specify "--format" explicitly.'
            )

        format_arg.value = inferred_format


format_group = Group(validator=_format_group_validator)


@app.command(default_parameter=Parameter(negative=""))
def generate_docs(
    script: str,
    output: Annotated[Path | None, Parameter(alias="-o", group=format_group)] = None,
    *,
    format: Annotated[
        DocFormat | None,
        Parameter(alias="-f", group=format_group),
    ] = None,
    include_hidden: bool = False,
    heading_level: int = 1,
):
    """Generate documentation for a Cyclopts application.

    Parameters
    ----------
    script : str
        Python script path, optionally with ``':app_object'`` notation to specify
        the App object. If not specified, will search for App objects in the
        script's global namespace.
    output : Optional[Path]
        Output file path. If not specified, prints to stdout.
    format : Optional[DocFormat]
        Output format for documentation. If not specified, inferred from output
        file extension.
    include_hidden : bool
        Include hidden commands in documentation.
    heading_level : int
        Starting heading level for markdown format.
    """
    if format is None:  # Handled by _format_group_validator
        raise ValueError("Must specify format.")
    format = normalize_format(format)
    app_obj, _ = load_app_from_script(script)
    docs_content = app_obj.generate_docs(
        output_format=format,
        include_hidden=include_hidden,
        heading_level=heading_level,
    )

    if output:
        output.write_text(docs_content)
    else:
        print(docs_content)
