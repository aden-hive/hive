"""
.. codeauthor:: Tsuyoshi Hombashi <tsuyoshi.hombashi@gmail.com>
"""

from typing import Union

import click
from click import Context, Option, Parameter

from ._filename import sanitize_filename, validate_filename
from ._filepath import sanitize_filepath, validate_filepath
from .error import ValidationError


def validate_filename_arg(ctx: Context, param: Union[Option, Parameter], value: str) -> str:
    if not value:
        return ""

    try:
        validate_filename(value)
    except ValidationError as e:
        raise click.BadParameter(str(e))

    return value


def validate_filepath_arg(ctx: Context, param: Union[Option, Parameter], value: str) -> str:
    if not value:
        return ""

    try:
        validate_filepath(value)
    except ValidationError as e:
        raise click.BadParameter(str(e))

    return value


def sanitize_filename_arg(ctx: Context, param: Union[Option, Parameter], value: str) -> str:
    if not value:
        return ""

    return sanitize_filename(value)


def sanitize_filepath_arg(ctx: Context, param: Union[Option, Parameter], value: str) -> str:
    if not value:
        return ""

    return sanitize_filepath(value)
