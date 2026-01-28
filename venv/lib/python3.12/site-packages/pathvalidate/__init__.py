"""
.. codeauthor:: Tsuyoshi Hombashi <tsuyoshi.hombashi@gmail.com>
"""

from .__version__ import __author__, __copyright__, __email__, __license__, __version__
from ._base import AbstractSanitizer, AbstractValidator
from ._common import (
    ascii_symbols,
    normalize_platform,
    replace_ansi_escape,
    replace_unprintable_char,
    unprintable_ascii_chars,
    validate_pathtype,
    validate_unprintable_char,
)
from ._const import Platform
from ._filename import (
    FileNameSanitizer,
    FileNameValidator,
    is_valid_filename,
    sanitize_filename,
    validate_filename,
)
from ._filepath import (
    FilePathSanitizer,
    FilePathValidator,
    is_valid_filepath,
    sanitize_filepath,
    validate_filepath,
)
from ._ltsv import sanitize_ltsv_label, validate_ltsv_label
from ._symbol import replace_symbol, validate_symbol
from .error import (
    ErrorReason,
    InvalidCharError,
    InvalidReservedNameError,
    NullNameError,
    ReservedNameError,
    ValidationError,
    ValidReservedNameError,
)


__all__ = (
    "__author__",
    "__copyright__",
    "__email__",
    "__license__",
    "__version__",
    "AbstractSanitizer",
    "AbstractValidator",
    "Platform",
    "ascii_symbols",
    "normalize_platform",
    "replace_ansi_escape",
    "replace_unprintable_char",
    "unprintable_ascii_chars",
    "validate_pathtype",
    "validate_unprintable_char",
    "FileNameSanitizer",
    "FileNameValidator",
    "is_valid_filename",
    "sanitize_filename",
    "validate_filename",
    "FilePathSanitizer",
    "FilePathValidator",
    "is_valid_filepath",
    "sanitize_filepath",
    "validate_filepath",
    "sanitize_ltsv_label",
    "validate_ltsv_label",
    "replace_symbol",
    "validate_symbol",
    "ErrorReason",
    "InvalidCharError",
    "InvalidReservedNameError",
    "NullNameError",
    "ReservedNameError",
    "ValidationError",
    "ValidReservedNameError",
)
