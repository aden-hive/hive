"""
.. codeauthor:: Tsuyoshi Hombashi <tsuyoshi.hombashi@gmail.com>
"""

import re
from collections.abc import Sequence
from typing import Final

from ._common import ascii_symbols, to_str, unprintable_ascii_chars
from .error import InvalidCharError


__RE_SYMBOL: Final = re.compile(
    "[{}]".format(re.escape("".join(ascii_symbols + unprintable_ascii_chars))), re.UNICODE
)


def validate_symbol(text: str) -> None:
    """
    Verifying whether symbol(s) included in the ``text`` or not.

    Args:
        text:
            Input text to validate.

    Raises:
        ValidationError (ErrorReason.INVALID_CHARACTER):
            If symbol(s) included in the ``text``.
    """

    match_list = __RE_SYMBOL.findall(to_str(text))
    if match_list:
        raise InvalidCharError(f"invalid symbols found: {match_list}")


def replace_symbol(
    text: str,
    replacement_text: str = "",
    exclude_symbols: Sequence[str] = [],
    is_replace_consecutive_chars: bool = False,
    is_strip: bool = False,
) -> str:
    """
    Replace all of the symbols in the ``text``.

    Args:
        text:
            Input text.
        replacement_text:
            Replacement text.
        exclude_symbols:
            Symbols that were excluded from the replacement.
        is_replace_consecutive_chars:
            If |True|, replace consecutive multiple ``replacement_text`` characters
            to a single character.
        is_strip:
            If |True|, strip ``replacement_text`` from the beginning/end of the replacement text.

    Returns:
        A replacement string.

    Example:

        :ref:`example-sanitize-symbol`
    """

    if exclude_symbols:
        regexp = re.compile(
            "[{}]".format(
                re.escape(
                    "".join(set(ascii_symbols + unprintable_ascii_chars) - set(exclude_symbols))
                )
            ),
            re.UNICODE,
        )
    else:
        regexp = __RE_SYMBOL

    try:
        new_text = regexp.sub(replacement_text, to_str(text))
    except TypeError:
        raise TypeError("text must be a string")

    if not replacement_text:
        return new_text

    if is_replace_consecutive_chars:
        new_text = re.sub(f"{re.escape(replacement_text)}+", replacement_text, new_text)

    if is_strip:
        new_text = new_text.strip(replacement_text)

    return new_text
