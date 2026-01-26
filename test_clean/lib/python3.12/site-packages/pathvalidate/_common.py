"""
.. codeauthor:: Tsuyoshi Hombashi <tsuyoshi.hombashi@gmail.com>
"""

import ntpath
import platform
import re
import string
import sys
from pathlib import PurePath
from typing import Any, Final, Optional

from ._const import Platform
from ._types import PathType, PlatformType


_re_whitespaces: Final = re.compile(r"^[\s]+$")


def validate_pathtype(
    text: PathType, allow_whitespaces: bool = False, error_msg: Optional[str] = None
) -> None:
    from .error import ErrorReason, ValidationError

    if _is_not_null_string(text) or isinstance(text, PurePath):
        return

    if allow_whitespaces and _re_whitespaces.search(str(text)):
        return

    if is_null_string(text):
        raise ValidationError(reason=ErrorReason.NULL_NAME)

    raise TypeError(f"text must be a string: actual={type(text)}")


def to_str(name: PathType) -> str:
    if isinstance(name, PurePath):
        return str(name)

    return name


def is_nt_abspath(value: str) -> bool:
    ver_info = sys.version_info[:2]
    if ver_info <= (3, 10):
        if value.startswith("\\\\"):
            return True
    elif ver_info >= (3, 13):
        return ntpath.isabs(value)

    drive, _tail = ntpath.splitdrive(value)

    return ntpath.isabs(value) and len(drive) > 0


def is_null_string(value: Any) -> bool:
    if value is None:
        return True

    try:
        return len(value.strip()) == 0
    except AttributeError:
        return False


def _is_not_null_string(value: Any) -> bool:
    try:
        return len(value.strip()) > 0
    except AttributeError:
        return False


def _get_unprintable_ascii_chars() -> list[str]:
    return [chr(c) for c in range(128) if chr(c) not in string.printable]


unprintable_ascii_chars: Final = tuple(_get_unprintable_ascii_chars())


def _get_ascii_symbols() -> list[str]:
    symbol_list: list[str] = []

    for i in range(128):
        c = chr(i)

        if c in unprintable_ascii_chars or c in string.digits + string.ascii_letters:
            continue

        symbol_list.append(c)

    return symbol_list


ascii_symbols: Final = tuple(_get_ascii_symbols())

__RE_UNPRINTABLE_CHARS: Final = re.compile(
    "[{}]".format(re.escape("".join(unprintable_ascii_chars))), re.UNICODE
)
__RE_ANSI_ESCAPE: Final = re.compile(
    r"(?:\x1B[@-Z\\-_]|[\x80-\x9A\x9C-\x9F]|(?:\x1B\[|\x9B)[0-?]*[ -/]*[@-~])"
)


def validate_unprintable_char(text: str) -> None:
    from .error import InvalidCharError

    match_list = __RE_UNPRINTABLE_CHARS.findall(to_str(text))
    if match_list:
        raise InvalidCharError(f"unprintable character found: {match_list}")


def replace_unprintable_char(text: str, replacement_text: str = "") -> str:
    try:
        return __RE_UNPRINTABLE_CHARS.sub(replacement_text, text)
    except (TypeError, AttributeError):
        raise TypeError("text must be a string")


def replace_ansi_escape(text: str, replacement_text: str = "") -> str:
    try:
        return __RE_ANSI_ESCAPE.sub(replacement_text, text)
    except (TypeError, AttributeError):
        raise TypeError("text must be a string")


def normalize_platform(name: Optional[PlatformType]) -> Platform:
    if isinstance(name, Platform):
        return name

    if not name:
        return Platform.UNIVERSAL

    platform_str = name.strip().casefold()

    if platform_str == "posix":
        return Platform.POSIX

    if platform_str == "auto":
        platform_str = platform.system().casefold()

    if platform_str in ["linux"]:
        return Platform.LINUX

    if platform_str and platform_str.startswith("win"):
        return Platform.WINDOWS

    if platform_str in ["mac", "macos", "darwin"]:
        return Platform.MACOS

    return Platform.UNIVERSAL


def findall_to_str(match: list[Any]) -> str:
    uniq_list = {repr(text) for text in match}
    return ", ".join(uniq_list)


def truncate_str(text: str, encoding: str, max_bytes: int) -> str:
    str_bytes = text.encode(encoding)
    str_bytes = str_bytes[:max_bytes]
    # last char might be malformed, ignore it
    return str_bytes.decode(encoding, "ignore")
