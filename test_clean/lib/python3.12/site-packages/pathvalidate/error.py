"""
.. codeauthor:: Tsuyoshi Hombashi <tsuyoshi.hombashi@gmail.com>
"""

import enum
from typing import Final, Optional

from ._const import Platform


def _to_error_code(code: int) -> str:
    return f"PV{code:04d}"


class ErrorAttrKey:
    BYTE_COUNT: Final = "byte_count"
    DESCRIPTION: Final = "description"
    FS_ENCODING: Final = "fs_encoding"
    PLATFORM: Final = "platform"
    REASON: Final = "reason"
    RESERVED_NAME: Final = "reserved_name"
    REUSABLE_NAME: Final = "reusable_name"
    VALUE: Final = "value"


@enum.unique
class ErrorReason(enum.Enum):
    """
    Validation error reasons.
    """

    NULL_NAME = (_to_error_code(1001), "NULL_NAME", "the value must not be an empty string")
    RESERVED_NAME = (
        _to_error_code(1002),
        "RESERVED_NAME",
        "found a reserved name by a platform",
    )
    INVALID_CHARACTER = (
        _to_error_code(1100),
        "INVALID_CHARACTER",
        "invalid characters found",
    )
    INVALID_LENGTH = (
        _to_error_code(1101),
        "INVALID_LENGTH",
        "found an invalid string length",
    )
    FOUND_ABS_PATH = (
        _to_error_code(1200),
        "FOUND_ABS_PATH",
        "found an absolute path where must be a relative path",
    )
    MALFORMED_ABS_PATH = (
        _to_error_code(1201),
        "MALFORMED_ABS_PATH",
        "found a malformed absolute path",
    )
    INVALID_AFTER_SANITIZE = (
        _to_error_code(2000),
        "INVALID_AFTER_SANITIZE",
        "found invalid value after sanitizing",
    )

    @property
    def code(self) -> str:
        """str: Error code."""
        return self.__code

    @property
    def name(self) -> str:
        """str: Error reason name."""
        return self.__name

    @property
    def description(self) -> str:
        """str: Error reason description."""
        return self.__description

    def __init__(self, code: str, name: str, description: str) -> None:
        self.__name = name
        self.__code = code
        self.__description = description

    def __str__(self) -> str:
        return f"[{self.__code}] {self.__description}"


class ValidationError(ValueError):
    """
    Exception class of validation errors.
    """

    @property
    def platform(self) -> Optional[Platform]:
        """
        :py:class:`~pathvalidate.Platform`: Platform information.
        """
        return self.__platform

    @property
    def reason(self) -> ErrorReason:
        """
        :py:class:`~pathvalidate.error.ErrorReason`: The cause of the error.
        """
        return self.__reason

    @property
    def description(self) -> Optional[str]:
        """Optional[str]: Error description."""
        return self.__description

    @property
    def reserved_name(self) -> str:
        """str: Reserved name."""
        return self.__reserved_name

    @property
    def reusable_name(self) -> Optional[bool]:
        """Optional[bool]: Whether the name is reusable or not."""
        return self.__reusable_name

    @property
    def fs_encoding(self) -> Optional[str]:
        """Optional[str]: File system encoding."""
        return self.__fs_encoding

    @property
    def byte_count(self) -> Optional[int]:
        """Optional[int]: Byte count of the path."""
        return self.__byte_count

    def __init__(self, *args, **kwargs) -> None:  # type: ignore
        if ErrorAttrKey.REASON not in kwargs:
            raise ValueError(f"{ErrorAttrKey.REASON} must be specified")

        self.__reason: ErrorReason = kwargs.pop(ErrorAttrKey.REASON)
        self.__byte_count: Optional[int] = kwargs.pop(ErrorAttrKey.BYTE_COUNT, None)
        self.__platform: Optional[Platform] = kwargs.pop(ErrorAttrKey.PLATFORM, None)
        self.__description: Optional[str] = kwargs.pop(ErrorAttrKey.DESCRIPTION, None)
        self.__reserved_name: str = kwargs.pop(ErrorAttrKey.RESERVED_NAME, "")
        self.__reusable_name: Optional[bool] = kwargs.pop(ErrorAttrKey.REUSABLE_NAME, None)
        self.__fs_encoding: Optional[str] = kwargs.pop(ErrorAttrKey.FS_ENCODING, None)
        self.__value: Optional[str] = kwargs.pop(ErrorAttrKey.VALUE, None)

        try:
            super().__init__(*args[0], **kwargs)
        except IndexError:
            super().__init__(*args, **kwargs)

    def as_slog(self) -> dict[str, str]:
        """Return a dictionary representation of the error.

        Returns:
            Dict[str, str]: A dictionary representation of the error.
        """

        slog: dict[str, str] = {
            "code": self.reason.code,
            ErrorAttrKey.DESCRIPTION: self.reason.description,
        }
        if self.platform:
            slog[ErrorAttrKey.PLATFORM] = self.platform.value
        if self.description:
            slog[ErrorAttrKey.DESCRIPTION] = self.description
        if self.__reusable_name is not None:
            slog[ErrorAttrKey.REUSABLE_NAME] = str(self.__reusable_name)
        if self.__fs_encoding:
            slog[ErrorAttrKey.FS_ENCODING] = self.__fs_encoding
        if self.__byte_count:
            slog[ErrorAttrKey.BYTE_COUNT] = str(self.__byte_count)
        if self.__value:
            slog[ErrorAttrKey.VALUE] = self.__value

        return slog

    def __str__(self) -> str:
        item_list = []
        header = str(self.reason)

        if Exception.__str__(self):
            item_list.append(Exception.__str__(self))

        if self.platform:
            item_list.append(f"{ErrorAttrKey.PLATFORM}={self.platform.value}")
        if self.description:
            item_list.append(f"{ErrorAttrKey.DESCRIPTION}={self.description}")
        if self.__reusable_name is not None:
            item_list.append(f"{ErrorAttrKey.REUSABLE_NAME}={self.reusable_name}")
        if self.__fs_encoding:
            item_list.append(f"{ErrorAttrKey.FS_ENCODING}={self.__fs_encoding}")
        if self.__byte_count is not None:
            item_list.append(f"{ErrorAttrKey.BYTE_COUNT}={self.__byte_count:,d}")
        if self.__value:
            item_list.append(f"{ErrorAttrKey.VALUE}={self.__value!r}")

        if item_list:
            header += ": "

        return header + ", ".join(item_list).strip()

    def __repr__(self) -> str:
        return self.__str__()


class NullNameError(ValidationError):
    """[Deprecated]
    Exception raised when a name is empty.
    """

    def __init__(self, *args, **kwargs) -> None:  # type: ignore
        kwargs[ErrorAttrKey.REASON] = ErrorReason.NULL_NAME

        super().__init__(args, **kwargs)


class InvalidCharError(ValidationError):
    """
    Exception raised when includes invalid character(s) within a string.
    """

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        kwargs[ErrorAttrKey.REASON] = ErrorReason.INVALID_CHARACTER

        super().__init__(args, **kwargs)


class ReservedNameError(ValidationError):
    """
    Exception raised when a string matched a reserved name.
    """

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        kwargs[ErrorAttrKey.REASON] = ErrorReason.RESERVED_NAME

        super().__init__(args, **kwargs)


class ValidReservedNameError(ReservedNameError):
    """[Deprecated]
    Exception raised when a string matched a reserved name.
    However, it can be used as a name.
    """

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        kwargs[ErrorAttrKey.REUSABLE_NAME] = True

        super().__init__(args, **kwargs)


class InvalidReservedNameError(ReservedNameError):
    """[Deprecated]
    Exception raised when a string matched a reserved name.
    Moreover, the reserved name is invalid as a name.
    """

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        kwargs[ErrorAttrKey.REUSABLE_NAME] = False

        super().__init__(args, **kwargs)
