"""
.. codeauthor:: Tsuyoshi Hombashi <tsuyoshi.hombashi@gmail.com>
"""

import itertools
import posixpath
import re
import warnings
from collections.abc import Sequence
from pathlib import Path, PurePath
from re import Pattern
from typing import Final, Optional

from ._base import AbstractSanitizer, AbstractValidator, BaseFile, BaseValidator
from ._common import findall_to_str, is_nt_abspath, to_str, truncate_str, validate_pathtype
from ._const import DEFAULT_MIN_LEN, INVALID_CHAR_ERR_MSG_TMPL, Platform
from ._types import PathType, PlatformType
from .error import ErrorAttrKey, ErrorReason, InvalidCharError, ValidationError
from .handler import ReservedNameHandler, ValidationErrorHandler


_DEFAULT_MAX_FILENAME_LEN: Final = 255
_RE_INVALID_FILENAME: Final = re.compile(
    f"[{re.escape(BaseFile._INVALID_FILENAME_CHARS):s}]", re.UNICODE
)
_RE_INVALID_WIN_FILENAME: Final = re.compile(
    f"[{re.escape(BaseFile._INVALID_WIN_FILENAME_CHARS):s}]", re.UNICODE
)


class FileNameSanitizer(AbstractSanitizer):
    def __init__(
        self,
        max_len: int = _DEFAULT_MAX_FILENAME_LEN,
        fs_encoding: Optional[str] = None,
        platform: Optional[PlatformType] = None,
        null_value_handler: Optional[ValidationErrorHandler] = None,
        reserved_name_handler: Optional[ValidationErrorHandler] = None,
        additional_reserved_names: Optional[Sequence[str]] = None,
        validate_after_sanitize: bool = False,
        validator: Optional[AbstractValidator] = None,
    ) -> None:
        if validator:
            fname_validator = validator
        else:
            fname_validator = FileNameValidator(
                min_len=DEFAULT_MIN_LEN,
                max_len=max_len,
                fs_encoding=fs_encoding,
                check_reserved=True,
                additional_reserved_names=additional_reserved_names,
                platform=platform,
            )

        super().__init__(
            max_len=max_len,
            fs_encoding=fs_encoding,
            null_value_handler=null_value_handler,
            reserved_name_handler=reserved_name_handler,
            additional_reserved_names=additional_reserved_names,
            platform=platform,
            validate_after_sanitize=validate_after_sanitize,
            validator=fname_validator,
        )

        self._sanitize_regexp = self._get_sanitize_regexp()

    def sanitize(self, value: PathType, replacement_text: str = "") -> PathType:
        try:
            validate_pathtype(value, allow_whitespaces=not self._is_windows(include_universal=True))
        except ValidationError as e:
            if e.reason == ErrorReason.NULL_NAME:
                if isinstance(value, PurePath):
                    raise

                return self._null_value_handler(e)  # type: ignore
            raise

        sanitized_filename = self._sanitize_regexp.sub(replacement_text, str(value))
        sanitized_filename = truncate_str(sanitized_filename, self._fs_encoding, self.max_len)

        try:
            self._validator.validate(sanitized_filename)
        except ValidationError as e:
            if e.reason == ErrorReason.RESERVED_NAME:
                replacement_word = self._reserved_name_handler(e)
                if e.reserved_name != replacement_word:
                    sanitized_filename = re.sub(
                        re.escape(e.reserved_name), replacement_word, sanitized_filename
                    )
            elif e.reason == ErrorReason.INVALID_CHARACTER and self._is_windows(
                include_universal=True
            ):
                # Do not start a file or directory name with a space
                sanitized_filename = sanitized_filename.lstrip(" ")

                # Do not end a file or directory name with a space or a period
                sanitized_filename = sanitized_filename.rstrip(" ")
                if sanitized_filename not in (".", ".."):
                    sanitized_filename = sanitized_filename.rstrip(" .")
            elif e.reason == ErrorReason.NULL_NAME:
                sanitized_filename = self._null_value_handler(e)

        if self._validate_after_sanitize:
            try:
                self._validator.validate(sanitized_filename)
            except ValidationError as e:
                raise ValidationError(
                    description=str(e),
                    reason=ErrorReason.INVALID_AFTER_SANITIZE,
                    platform=self.platform,
                )

        if isinstance(value, PurePath):
            return Path(sanitized_filename)  # type: ignore

        return sanitized_filename  # type: ignore

    def _get_sanitize_regexp(self) -> Pattern[str]:
        if self._is_windows(include_universal=True):
            return _RE_INVALID_WIN_FILENAME

        return _RE_INVALID_FILENAME


class FileNameValidator(BaseValidator):
    _WINDOWS_RESERVED_FILE_NAMES: Final = (
        ("CON", "PRN", "AUX", "CLOCK$", "NUL")
        + tuple(f"{name:s}{num:d}" for name, num in itertools.product(("COM", "LPT"), range(0, 10)))
        + tuple(
            f"{name:s}{ssd:s}"
            for name, ssd in itertools.product(
                ("COM", "LPT"),
                ("\N{SUPERSCRIPT ONE}", "\N{SUPERSCRIPT TWO}", "\N{SUPERSCRIPT THREE}"),
            )
        )
    )
    _MACOS_RESERVED_FILE_NAMES: Final = (":",)

    @property
    def reserved_keywords(self) -> tuple[str, ...]:
        common_keywords = super().reserved_keywords

        if self._is_universal():
            word_set = set(
                common_keywords
                + self._WINDOWS_RESERVED_FILE_NAMES
                + self._MACOS_RESERVED_FILE_NAMES
            )
        elif self._is_windows():
            word_set = set(common_keywords + self._WINDOWS_RESERVED_FILE_NAMES)
        elif self._is_posix() or self._is_macos():
            word_set = set(common_keywords + self._MACOS_RESERVED_FILE_NAMES)
        else:
            word_set = set(common_keywords)

        return tuple(sorted(word_set))

    def __init__(
        self,
        min_len: int = DEFAULT_MIN_LEN,
        max_len: int = _DEFAULT_MAX_FILENAME_LEN,
        fs_encoding: Optional[str] = None,
        platform: Optional[PlatformType] = None,
        check_reserved: bool = True,
        additional_reserved_names: Optional[Sequence[str]] = None,
    ) -> None:
        super().__init__(
            min_len=min_len,
            max_len=max_len,
            fs_encoding=fs_encoding,
            check_reserved=check_reserved,
            additional_reserved_names=additional_reserved_names,
            platform=platform,
        )

    def validate(self, value: PathType) -> None:
        validate_pathtype(value, allow_whitespaces=not self._is_windows(include_universal=True))

        unicode_filename = to_str(value)
        byte_ct = len(unicode_filename.encode(self._fs_encoding))

        self.validate_abspath(unicode_filename)

        err_kwargs = {
            ErrorAttrKey.REASON: ErrorReason.INVALID_LENGTH,
            ErrorAttrKey.PLATFORM: self.platform,
            ErrorAttrKey.FS_ENCODING: self._fs_encoding,
            ErrorAttrKey.BYTE_COUNT: byte_ct,
            ErrorAttrKey.VALUE: unicode_filename,
        }
        if byte_ct > self.max_len:
            raise ValidationError(
                [
                    f"filename is too long: expected<={self.max_len:d} bytes, actual={byte_ct:d} bytes"
                ],
                **err_kwargs,
            )
        if byte_ct < self.min_len:
            raise ValidationError(
                [
                    f"filename is too short: expected>={self.min_len:d} bytes, actual={byte_ct:d} bytes"
                ],
                **err_kwargs,
            )

        self._validate_reserved_keywords(unicode_filename)
        self.__validate_universal_filename(unicode_filename)

        if self._is_windows(include_universal=True):
            self.__validate_win_filename(unicode_filename)

    def validate_abspath(self, value: str) -> None:
        err = ValidationError(
            description=f"found an absolute path ({value!r}), expected a filename",
            platform=self.platform,
            reason=ErrorReason.FOUND_ABS_PATH,
        )

        if self._is_windows(include_universal=True):
            if is_nt_abspath(value):
                raise err

        if posixpath.isabs(value):
            raise err

    def __validate_universal_filename(self, unicode_filename: str) -> None:
        match = _RE_INVALID_FILENAME.findall(unicode_filename)
        if match:
            raise InvalidCharError(
                INVALID_CHAR_ERR_MSG_TMPL.format(
                    invalid=findall_to_str(match),
                ),
                platform=Platform.UNIVERSAL,
                value=unicode_filename,
            )

    def __validate_win_filename(self, unicode_filename: str) -> None:
        match = _RE_INVALID_WIN_FILENAME.findall(unicode_filename)
        if match:
            raise InvalidCharError(
                INVALID_CHAR_ERR_MSG_TMPL.format(
                    invalid=findall_to_str(match),
                ),
                platform=Platform.WINDOWS,
                value=unicode_filename,
            )

        if unicode_filename in (".", ".."):
            return

        KB2829981_err_tmpl = "{}. Refer: https://learn.microsoft.com/en-us/troubleshoot/windows-client/shell-experience/file-folder-name-whitespace-characters"  # noqa: E501
        err_kwargs = {
            ErrorAttrKey.PLATFORM: Platform.WINDOWS,
            ErrorAttrKey.VALUE: unicode_filename,
        }

        if unicode_filename[-1] in (" ", "."):
            raise InvalidCharError(
                INVALID_CHAR_ERR_MSG_TMPL.format(invalid=re.escape(unicode_filename[-1])),
                description=KB2829981_err_tmpl.format(
                    "Do not end a file or directory name with a space or a period"
                ),
                **err_kwargs,
            )

        if unicode_filename[0] in (" "):
            raise InvalidCharError(
                INVALID_CHAR_ERR_MSG_TMPL.format(invalid=re.escape(unicode_filename[0])),
                description=KB2829981_err_tmpl.format(
                    "Do not start a file or directory name with a space"
                ),
                **err_kwargs,
            )


def validate_filename(
    filename: PathType,
    platform: Optional[PlatformType] = None,
    min_len: int = DEFAULT_MIN_LEN,
    max_len: int = _DEFAULT_MAX_FILENAME_LEN,
    fs_encoding: Optional[str] = None,
    check_reserved: bool = True,
    additional_reserved_names: Optional[Sequence[str]] = None,
) -> None:
    """Verifying whether the ``filename`` is a valid file name or not.

    Args:
        filename:
            Filename to validate.
        platform:
            Target platform name of the filename.

            .. include:: platform.txt
        min_len:
            Minimum byte length of the ``filename``. The value must be greater or equal to one.
            Defaults to ``1``.
        max_len:
            Maximum byte length of the ``filename``. The value must be lower than:

                - ``Linux``: 4096
                - ``macOS``: 1024
                - ``Windows``: 260
                - ``universal``: 260

            Defaults to ``255``.
        fs_encoding:
            Filesystem encoding that is used to calculate the byte length of the filename.
            If |None|, get the encoding from the execution environment.
        check_reserved:
            If |True|, check the reserved names of the ``platform``.
        additional_reserved_names:
            Additional reserved names to check.
            Case insensitive.

    Raises:
        ValidationError (ErrorReason.INVALID_LENGTH):
            If the ``filename`` is longer than ``max_len`` characters.
        ValidationError (ErrorReason.INVALID_CHARACTER):
            If the ``filename`` includes invalid character(s) for a filename:
            |invalid_filename_chars|.
            The following characters are also invalid for Windows platforms:
            |invalid_win_filename_chars|.
        ValidationError (ErrorReason.RESERVED_NAME):
            If the ``filename`` equals the reserved name by OS.
            Windows reserved name is as follows:
            ``"CON"``, ``"PRN"``, ``"AUX"``, ``"NUL"``, ``"COM[1-9]"``, ``"LPT[1-9]"``.

    Example:
        :ref:`example-validate-filename`

    See Also:
        `Naming Files, Paths, and Namespaces - Win32 apps | Microsoft Docs
        <https://docs.microsoft.com/en-us/windows/win32/fileio/naming-a-file>`__
    """

    FileNameValidator(
        platform=platform,
        min_len=min_len,
        max_len=max_len,
        fs_encoding=fs_encoding,
        check_reserved=check_reserved,
        additional_reserved_names=additional_reserved_names,
    ).validate(filename)


def is_valid_filename(
    filename: PathType,
    platform: Optional[PlatformType] = None,
    min_len: int = DEFAULT_MIN_LEN,
    max_len: Optional[int] = None,
    fs_encoding: Optional[str] = None,
    check_reserved: bool = True,
    additional_reserved_names: Optional[Sequence[str]] = None,
) -> bool:
    """Check whether the ``filename`` is a valid name or not.

    Args:
        filename:
            A filename to be checked.
        platform:
            Target platform name of the filename.

    Example:
        :ref:`example-is-valid-filename`

    See Also:
        :py:func:`.validate_filename()`
    """

    return FileNameValidator(
        platform=platform,
        min_len=min_len,
        max_len=-1 if max_len is None else max_len,
        fs_encoding=fs_encoding,
        check_reserved=check_reserved,
        additional_reserved_names=additional_reserved_names,
    ).is_valid(filename)


def sanitize_filename(
    filename: PathType,
    replacement_text: str = "",
    platform: Optional[PlatformType] = None,
    max_len: Optional[int] = _DEFAULT_MAX_FILENAME_LEN,
    fs_encoding: Optional[str] = None,
    check_reserved: Optional[bool] = None,
    null_value_handler: Optional[ValidationErrorHandler] = None,
    reserved_name_handler: Optional[ValidationErrorHandler] = None,
    additional_reserved_names: Optional[Sequence[str]] = None,
    validate_after_sanitize: bool = False,
) -> PathType:
    """Make a valid filename from a string.

    To make a valid filename, the function does the following:

        - Replace invalid characters as file names included in the ``filename``
          with the ``replacement_text``. Invalid characters are:

            - unprintable characters
            - |invalid_filename_chars|
            - for Windows (or universal) only: |invalid_win_filename_chars|

        - Replace a value if a sanitized value is a reserved name by operating systems
          with a specified handler by ``reserved_name_handler``.

    Args:
        filename: Filename to sanitize.
        replacement_text:
            Replacement text for invalid characters. Defaults to ``""``.
        platform:
            Target platform name of the filename.

            .. include:: platform.txt
        max_len:
            Maximum byte length of the ``filename``.
            Truncate the name length if the ``filename`` length exceeds this value.
            Defaults to ``255``.
        fs_encoding:
            Filesystem encoding that is used to calculate the byte length of the filename.
            If |None|, get the encoding from the execution environment.
        check_reserved:
            [Deprecated] Use 'reserved_name_handler' instead.
        null_value_handler:
            Function called when a value after sanitization is an empty string.
            You can specify predefined handlers:

                - :py:func:`~.handler.NullValueHandler.return_null_string`
                - :py:func:`~.handler.NullValueHandler.return_timestamp`
                - :py:func:`~.handler.raise_error`

            Defaults to :py:func:`.handler.NullValueHandler.return_null_string` that just return ``""``.
        reserved_name_handler:
            Function called when a value after sanitization is a reserved name.
            You can specify predefined handlers:

                - :py:meth:`~.handler.ReservedNameHandler.add_leading_underscore`
                - :py:meth:`~.handler.ReservedNameHandler.add_trailing_underscore`
                - :py:meth:`~.handler.ReservedNameHandler.as_is`
                - :py:func:`~.handler.raise_error`

            Defaults to :py:func:`.handler.add_trailing_underscore`.
        additional_reserved_names:
            Additional reserved names to sanitize.
            Case insensitive.
        validate_after_sanitize:
            Execute validation after sanitization to the file name.

    Returns:
        Same type as the ``filename`` (str or PathLike object):
            Sanitized filename.

    Raises:
        ValueError:
            If the ``filename`` is an invalid filename.

    Example:
        :ref:`example-sanitize-filename`
    """

    if check_reserved is not None:
        warnings.warn(
            "'check_reserved' is deprecated. Use 'reserved_name_handler' instead.",
            DeprecationWarning,
        )

        if check_reserved is False:
            reserved_name_handler = ReservedNameHandler.as_is

    return FileNameSanitizer(
        platform=platform,
        max_len=-1 if max_len is None else max_len,
        fs_encoding=fs_encoding,
        null_value_handler=null_value_handler,
        reserved_name_handler=reserved_name_handler,
        additional_reserved_names=additional_reserved_names,
        validate_after_sanitize=validate_after_sanitize,
    ).sanitize(filename, replacement_text)
