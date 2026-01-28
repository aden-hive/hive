"""
.. codeauthor:: Tsuyoshi Hombashi <tsuyoshi.hombashi@gmail.com>
"""

from argparse import ArgumentTypeError

from ._filename import sanitize_filename, validate_filename
from ._filepath import sanitize_filepath, validate_filepath
from .error import ValidationError


def validate_filename_arg(value: str) -> str:
    if not value:
        return ""

    try:
        validate_filename(value)
    except ValidationError as e:
        raise ArgumentTypeError(e)

    return value


def validate_filepath_arg(value: str) -> str:
    if not value:
        return ""

    try:
        validate_filepath(value, platform="auto")
    except ValidationError as e:
        raise ArgumentTypeError(e)

    return value


def sanitize_filename_arg(value: str) -> str:
    if not value:
        return ""

    return sanitize_filename(value)


def sanitize_filepath_arg(value: str) -> str:
    if not value:
        return ""

    return sanitize_filepath(value, platform="auto")
