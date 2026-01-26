"""
.. codeauthor:: Tsuyoshi Hombashi <tsuyoshi.hombashi@gmail.com>
"""

import ntpath
import os.path
import posixpath
import re
import warnings
from collections.abc import Sequence
from pathlib import Path, PurePath
from re import Pattern
from typing import Final, Optional

from ._base import AbstractSanitizer, AbstractValidator, BaseFile, BaseValidator
from ._common import findall_to_str, is_nt_abspath, to_str, validate_pathtype
from ._const import _NTFS_RESERVED_FILE_NAMES, DEFAULT_MIN_LEN, INVALID_CHAR_ERR_MSG_TMPL, Platform
from ._filename import FileNameSanitizer, FileNameValidator
from ._types import PathType, PlatformType
from .error import ErrorAttrKey, ErrorReason, InvalidCharError, ReservedNameError, ValidationError
from .handler import ReservedNameHandler, ValidationErrorHandler


_RE_INVALID_PATH: Final = re.compile(f"[{re.escape(BaseFile._INVALID_PATH_CHARS):s}]", re.UNICODE)
_RE_INVALID_WIN_PATH: Final = re.compile(
    f"[{re.escape(BaseFile._INVALID_WIN_PATH_CHARS):s}]", re.UNICODE
)


class FilePathSanitizer(AbstractSanitizer):
    def __init__(
        self,
        max_len: int = -1,
        fs_encoding: Optional[str] = None,
        platform: Optional[PlatformType] = None,
        null_value_handler: Optional[ValidationErrorHandler] = None,
        reserved_name_handler: Optional[ValidationErrorHandler] = None,
        additional_reserved_names: Optional[Sequence[str]] = None,
        normalize: bool = True,
        validate_after_sanitize: bool = False,
        validator: Optional[AbstractValidator] = None,
    ) -> None:
        if validator:
            fpath_validator = validator
        else:
            fpath_validator = FilePathValidator(
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
            validator=fpath_validator,
            null_value_handler=null_value_handler,
            reserved_name_handler=reserved_name_handler,
            additional_reserved_names=additional_reserved_names,
            platform=platform,
            validate_after_sanitize=validate_after_sanitize,
        )

        self._sanitize_regexp = self._get_sanitize_regexp()
        self.__fname_sanitizer = FileNameSanitizer(
            max_len=self.max_len,
            fs_encoding=fs_encoding,
            null_value_handler=null_value_handler,
            reserved_name_handler=reserved_name_handler,
            additional_reserved_names=additional_reserved_names,
            platform=self.platform,
            validate_after_sanitize=validate_after_sanitize,
        )
        self.__normalize = normalize

        if self._is_windows(include_universal=True):
            self.__split_drive = ntpath.splitdrive
        else:
            self.__split_drive = posixpath.splitdrive

    def sanitize(self, value: PathType, replacement_text: str = "") -> PathType:
        try:
            validate_pathtype(value, allow_whitespaces=not self._is_windows(include_universal=True))
        except ValidationError as e:
            if e.reason == ErrorReason.NULL_NAME:
                if isinstance(value, PurePath):
                    raise

                return self._null_value_handler(e)  # type: ignore
            raise

        unicode_filepath = to_str(value)
        drive, unicode_filepath = self.__split_drive(unicode_filepath)
        unicode_filepath = self._sanitize_regexp.sub(replacement_text, unicode_filepath)
        if self.__normalize and unicode_filepath:
            unicode_filepath = os.path.normpath(unicode_filepath)
        sanitized_path = unicode_filepath

        sanitized_entries: list[str] = []
        if drive:
            sanitized_entries.append(drive)
        for entry in sanitized_path.replace("\\", "/").split("/"):
            if entry in _NTFS_RESERVED_FILE_NAMES:
                sanitized_entries.append(f"{entry}_")
                continue

            sanitized_entry = str(
                self.__fname_sanitizer.sanitize(entry, replacement_text=replacement_text)
            )
            if not sanitized_entry:
                if not sanitized_entries:
                    sanitized_entries.append("")
                continue

            sanitized_entries.append(sanitized_entry)

        sanitized_path = self.__get_path_separator().join(sanitized_entries)
        try:
            self._validator.validate(sanitized_path)
        except ValidationError as e:
            if e.reason == ErrorReason.NULL_NAME:
                sanitized_path = self._null_value_handler(e)

        if self._validate_after_sanitize:
            self._validator.validate(sanitized_path)

        if isinstance(value, PurePath):
            return Path(sanitized_path)  # type: ignore

        return sanitized_path  # type: ignore

    def _get_sanitize_regexp(self) -> Pattern[str]:
        if self._is_windows(include_universal=True):
            return _RE_INVALID_WIN_PATH

        return _RE_INVALID_PATH

    def __get_path_separator(self) -> str:
        if self._is_windows():
            return "\\"

        return "/"


class FilePathValidator(BaseValidator):
    _RE_NTFS_RESERVED: Final = re.compile(
        "|".join(f"^/{re.escape(pattern)}$" for pattern in _NTFS_RESERVED_FILE_NAMES),
        re.IGNORECASE,
    )
    _MACOS_RESERVED_FILE_PATHS: Final = ("/", ":")

    @property
    def reserved_keywords(self) -> tuple[str, ...]:
        common_keywords = super().reserved_keywords

        if any([self._is_universal(), self._is_posix(), self._is_macos()]):
            return common_keywords + self._MACOS_RESERVED_FILE_PATHS

        if self._is_linux():
            return common_keywords + ("/",)

        return common_keywords

    def __init__(
        self,
        min_len: int = DEFAULT_MIN_LEN,
        max_len: int = -1,
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

        self.__fname_validator = FileNameValidator(
            min_len=min_len,
            max_len=self.max_len,
            fs_encoding=fs_encoding,
            check_reserved=check_reserved,
            additional_reserved_names=additional_reserved_names,
            platform=platform,
        )

        if self._is_windows(include_universal=True):
            self.__split_drive = ntpath.splitdrive
        else:
            self.__split_drive = posixpath.splitdrive

    def validate(self, value: PathType) -> None:
        validate_pathtype(value, allow_whitespaces=not self._is_windows(include_universal=True))
        self.validate_abspath(value)

        _drive, tail = self.__split_drive(value)
        if not tail:
            return

        unicode_filepath = to_str(tail)
        byte_ct = len(unicode_filepath.encode(self._fs_encoding))
        err_kwargs = {
            ErrorAttrKey.REASON: ErrorReason.INVALID_LENGTH,
            ErrorAttrKey.PLATFORM: self.platform,
            ErrorAttrKey.FS_ENCODING: self._fs_encoding,
            ErrorAttrKey.BYTE_COUNT: byte_ct,
            ErrorAttrKey.VALUE: unicode_filepath,
        }

        if byte_ct > self.max_len:
            raise ValidationError(
                [
                    f"file path is too long: expected<={self.max_len:d} bytes, actual={byte_ct:d} bytes"
                ],
                **err_kwargs,
            )
        if byte_ct < self.min_len:
            raise ValidationError(
                [
                    "file path is too short: expected>={:d} bytes, actual={:d} bytes".format(
                        self.min_len, byte_ct
                    )
                ],
                **err_kwargs,
            )

        self._validate_reserved_keywords(unicode_filepath)
        unicode_filepath = unicode_filepath.replace("\\", "/")
        for entry in unicode_filepath.split("/"):
            if not entry or entry in (".", ".."):
                continue

            self.__fname_validator.validate(entry)

        if self._is_windows(include_universal=True):
            self.__validate_win_filepath(unicode_filepath)
        else:
            self.__validate_unix_filepath(unicode_filepath)

    def validate_abspath(self, value: PathType) -> None:
        is_posix_abs = posixpath.isabs(value)
        is_nt_abs = is_nt_abspath(to_str(value))

        if any([self._is_windows() and is_nt_abs, self._is_posix() and is_posix_abs]):
            return

        if self._is_universal() and any([is_nt_abs, is_posix_abs]):
            ValidationError(
                "platform-independent absolute file path is not supported",
                platform=self.platform,
                reason=ErrorReason.MALFORMED_ABS_PATH,
            )

        err_object = ValidationError(
            description=(
                f"an invalid absolute file path ({value!r}) for the platform ({self.platform.value})."
                + " to avoid the error, specify an appropriate platform corresponding to"
                + " the path format or 'auto'."
            ),
            platform=self.platform,
            reason=ErrorReason.MALFORMED_ABS_PATH,
        )

        if self._is_windows(include_universal=True) and is_posix_abs:
            raise err_object

        if not self._is_windows():
            drive, _tail = ntpath.splitdrive(value)
            if drive and is_nt_abs:
                raise err_object

    def __validate_unix_filepath(self, unicode_filepath: str) -> None:
        match = _RE_INVALID_PATH.findall(unicode_filepath)
        if match:
            raise InvalidCharError(
                INVALID_CHAR_ERR_MSG_TMPL.format(invalid=findall_to_str(match)),
                value=unicode_filepath,
            )

    def __validate_win_filepath(self, unicode_filepath: str) -> None:
        match = _RE_INVALID_WIN_PATH.findall(unicode_filepath)
        if match:
            raise InvalidCharError(
                INVALID_CHAR_ERR_MSG_TMPL.format(invalid=findall_to_str(match)),
                platform=Platform.WINDOWS,
                value=unicode_filepath,
            )

        _drive, value = self.__split_drive(unicode_filepath)
        if value:
            match_reserved = self._RE_NTFS_RESERVED.search(value)
            if match_reserved:
                reserved_name = match_reserved.group()
                raise ReservedNameError(
                    f"'{reserved_name}' is a reserved name",
                    reusable_name=False,
                    reserved_name=reserved_name,
                    platform=self.platform,
                )


def validate_filepath(
    file_path: PathType,
    platform: Optional[PlatformType] = None,
    min_len: int = DEFAULT_MIN_LEN,
    max_len: Optional[int] = None,
    fs_encoding: Optional[str] = None,
    check_reserved: bool = True,
    additional_reserved_names: Optional[Sequence[str]] = None,
) -> None:
    """Verifying whether the ``file_path`` is a valid file path or not.

    Args:
        file_path (PathType):
            File path to be validated.
        platform (Optional[PlatformType], optional):
            Target platform name of the file path.

            .. include:: platform.txt
        min_len (int, optional):
            Minimum byte length of the ``file_path``. The value must be greater or equal to one.
            Defaults to ``1``.
        max_len (Optional[int], optional):
            Maximum byte length of the ``file_path``. If the value is |None| or minus,
            automatically determined by the ``platform``:

                - ``Linux``: 4096
                - ``macOS``: 1024
                - ``Windows``: 260
                - ``universal``: 260
        fs_encoding (Optional[str], optional):
            Filesystem encoding that is used to calculate the byte length of the file path.
            If |None|, get the encoding from the execution environment.
        check_reserved (bool, optional):
            If |True|, check the reserved names of the ``platform``.
            Defaults to |True|.
        additional_reserved_names (Optional[Sequence[str]], optional):
            Additional reserved names to check.

    Raises:
        ValidationError (ErrorReason.INVALID_CHARACTER):
            If the ``file_path`` includes invalid char(s):
            |invalid_file_path_chars|.
            The following characters are also invalid for Windows platforms:
            |invalid_win_file_path_chars|
        ValidationError (ErrorReason.INVALID_LENGTH):
            If the ``file_path`` is longer than ``max_len`` characters.
        ValidationError:
            If ``file_path`` includes invalid values.

    Example:
        :ref:`example-validate-file-path`

    See Also:
        `Naming Files, Paths, and Namespaces - Win32 apps | Microsoft Docs
        <https://docs.microsoft.com/en-us/windows/win32/fileio/naming-a-file>`__
    """

    FilePathValidator(
        platform=platform,
        min_len=min_len,
        max_len=-1 if max_len is None else max_len,
        fs_encoding=fs_encoding,
        check_reserved=check_reserved,
        additional_reserved_names=additional_reserved_names,
    ).validate(file_path)


def is_valid_filepath(
    file_path: PathType,
    platform: Optional[PlatformType] = None,
    min_len: int = DEFAULT_MIN_LEN,
    max_len: Optional[int] = None,
    fs_encoding: Optional[str] = None,
    check_reserved: bool = True,
    additional_reserved_names: Optional[Sequence[str]] = None,
) -> bool:
    """Check whether the ``file_path`` is a valid name or not.

    Args:
        file_path:
            A filepath to be checked.
        platform:
            Target platform name of the file path.

    Example:
        :ref:`example-is-valid-filepath`

    See Also:
        :py:func:`.validate_filepath()`
    """

    return FilePathValidator(
        platform=platform,
        min_len=min_len,
        max_len=-1 if max_len is None else max_len,
        fs_encoding=fs_encoding,
        check_reserved=check_reserved,
        additional_reserved_names=additional_reserved_names,
    ).is_valid(file_path)


def sanitize_filepath(
    file_path: PathType,
    replacement_text: str = "",
    platform: Optional[PlatformType] = None,
    max_len: Optional[int] = None,
    fs_encoding: Optional[str] = None,
    check_reserved: Optional[bool] = None,
    null_value_handler: Optional[ValidationErrorHandler] = None,
    reserved_name_handler: Optional[ValidationErrorHandler] = None,
    additional_reserved_names: Optional[Sequence[str]] = None,
    normalize: bool = True,
    validate_after_sanitize: bool = False,
) -> PathType:
    """Make a valid file path from a string.

    To make a valid file path, the function does the following:

        - Replace invalid characters for a file path within the ``file_path``
          with the ``replacement_text``. Invalid characters are as follows:

            - unprintable characters
            - |invalid_file_path_chars|
            - for Windows (or universal) only: |invalid_win_file_path_chars|

        - Replace a value if a sanitized value is a reserved name by operating systems
          with a specified handler by ``reserved_name_handler``.

    Args:
        file_path:
            File path to sanitize.
        replacement_text:
            Replacement text for invalid characters.
            Defaults to ``""``.
        platform:
            Target platform name of the file path.

            .. include:: platform.txt
        max_len:
            Maximum byte length of the file path.
            Truncate the path if the value length exceeds the `max_len`.
            If the value is |None| or minus, ``max_len`` will automatically determined by the ``platform``:

                - ``Linux``: 4096
                - ``macOS``: 1024
                - ``Windows``: 260
                - ``universal``: 260
        fs_encoding:
            Filesystem encoding that is used to calculate the byte length of the file path.
            If |None|, get the encoding from the execution environment.
        check_reserved:
            [Deprecated] Use 'reserved_name_handler' instead.
        null_value_handler:
            Function called when a value after sanitization is an empty string.
            You can specify predefined handlers:

                - :py:func:`.handler.NullValueHandler.return_null_string`
                - :py:func:`.handler.NullValueHandler.return_timestamp`
                - :py:func:`.handler.raise_error`

            Defaults to :py:func:`.handler.NullValueHandler.return_null_string` that just return ``""``.
        reserved_name_handler:
            Function called when a value after sanitization is one of the reserved names.
            You can specify predefined handlers:

                - :py:meth:`~.handler.ReservedNameHandler.add_leading_underscore`
                - :py:meth:`~.handler.ReservedNameHandler.add_trailing_underscore`
                - :py:meth:`~.handler.ReservedNameHandler.as_is`
                - :py:func:`~.handler.raise_error`

            Defaults to :py:func:`.handler.add_trailing_underscore`.
        additional_reserved_names:
            Additional reserved names to sanitize.
            Case insensitive.
        normalize:
            If |True|, normalize the the file path.
        validate_after_sanitize:
            Execute validation after sanitization to the file path.

    Returns:
        Same type as the argument (str or PathLike object):
            Sanitized filepath.

    Raises:
        ValueError:
            If the ``file_path`` is an invalid file path.

    Example:
        :ref:`example-sanitize-file-path`
    """

    if check_reserved is not None:
        warnings.warn(
            "'check_reserved' is deprecated. Use 'reserved_name_handler' instead.",
            DeprecationWarning,
        )

        if check_reserved is False:
            reserved_name_handler = ReservedNameHandler.as_is

    return FilePathSanitizer(
        platform=platform,
        max_len=-1 if max_len is None else max_len,
        fs_encoding=fs_encoding,
        normalize=normalize,
        null_value_handler=null_value_handler,
        reserved_name_handler=reserved_name_handler,
        additional_reserved_names=additional_reserved_names,
        validate_after_sanitize=validate_after_sanitize,
    ).sanitize(file_path, replacement_text)
