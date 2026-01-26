"""
.. codeauthor:: Tsuyoshi Hombashi <tsuyoshi.hombashi@gmail.com>
"""

import re
from typing import Final

from ._common import to_str, validate_pathtype
from .error import InvalidCharError


__RE_INVALID_LTSV_LABEL: Final = re.compile("[^0-9A-Za-z_.-]", re.UNICODE)


def validate_ltsv_label(label: str) -> None:
    """
    Verifying whether ``label`` is a valid
    `Labeled Tab-separated Values (LTSV) <http://ltsv.org/>`__ label or not.

    :param label: Label to validate.
    :raises pathvalidate.ValidationError:
        If invalid character(s) found in the ``label`` for a LTSV format label.
    """

    validate_pathtype(label, allow_whitespaces=False)

    match_list = __RE_INVALID_LTSV_LABEL.findall(to_str(label))
    if match_list:
        raise InvalidCharError(f"invalid character found for a LTSV format label: {match_list}")


def sanitize_ltsv_label(label: str, replacement_text: str = "") -> str:
    """
    Replace all of the symbols in text.

    :param label: Input text.
    :param replacement_text: Replacement text.
    :return: A replacement string.
    :rtype: str
    """

    validate_pathtype(label, allow_whitespaces=False)

    return __RE_INVALID_LTSV_LABEL.sub(replacement_text, to_str(label))
