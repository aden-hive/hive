import json
import sys
from collections.abc import Sequence
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

from cyclopts import validators
from cyclopts.parameter import Parameter

if TYPE_CHECKING:
    from cyclopts._path_type import StdioPath as StdioPath
    from cyclopts.token import Token

__all__ = [
    # Path
    "StdioPath",
    "ExistingPath",
    "NonExistentPath",
    "ExistingFile",
    "NonExistentFile",
    "ExistingDirectory",
    "NonExistentDirectory",
    "Directory",
    "File",
    "ResolvedExistingPath",
    "ResolvedExistingFile",
    "ResolvedExistingDirectory",
    "ResolvedDirectory",
    "ResolvedFile",
    "ResolvedPath",
    # Path with extensions
    "BinPath",
    "ExistingBinPath",
    "NonExistentBinPath",
    "CsvPath",
    "ExistingCsvPath",
    "NonExistentCsvPath",
    "ImagePath",
    "ExistingImagePath",
    "NonExistentImagePath",
    "JsonPath",
    "ExistingJsonPath",
    "NonExistentJsonPath",
    "Mp4Path",
    "ExistingMp4Path",
    "NonExistentMp4Path",
    "TomlPath",
    "ExistingTomlPath",
    "NonExistentTomlPath",
    "TxtPath",
    "ExistingTxtPath",
    "NonExistentTxtPath",
    "YamlPath",
    "ExistingYamlPath",
    "NonExistentYamlPath",
    # Number
    "PositiveFloat",
    "NonNegativeFloat",
    "NegativeFloat",
    "NonPositiveFloat",
    "PositiveInt",
    "NonNegativeInt",
    "NegativeInt",
    "NonPositiveInt",
    "UInt8",
    "Int8",
    "UInt16",
    "Int16",
    "UInt32",
    "Int32",
    "UInt64",
    "Int64",
    "HexUInt",
    "HexUInt8",
    "HexUInt16",
    "HexUInt32",
    "HexUInt64",
    # Json,
    "Json",
    # Web
    "Email",
    "Port",
    "URL",
]


########
# Path #
########
def _path_resolve_converter(type_, tokens: Sequence["Token"]):
    assert len(tokens) == 1
    return type_(tokens[0].value).resolve()


ExistingPath = Annotated[Path, Parameter(validator=validators.Path(exists=True))]
"A :class:`~pathlib.Path` file or directory that **must** exist."

NonExistentPath = Annotated[Path, Parameter(validator=validators.Path(file_okay=False, dir_okay=False))]
"A :class:`~pathlib.Path` file or directory that **must not** exist."

ResolvedPath = Annotated[Path, Parameter(converter=_path_resolve_converter)]
"A :class:`~pathlib.Path` file or directory. :meth:`~pathlib.Path.resolve` is invoked prior to returning the path."
ResolvedExistingPath = Annotated[ExistingPath, Parameter(converter=_path_resolve_converter)]
"A :class:`~pathlib.Path` file or directory that **must** exist. :meth:`~pathlib.Path.resolve` is invoked prior to returning the path."

Directory = Annotated[Path, Parameter(validator=validators.Path(file_okay=False))]
"A :class:`~pathlib.Path` that **must** be a directory (or not exist)."
ExistingDirectory = Annotated[Path, Parameter(validator=validators.Path(exists=True, file_okay=False))]
"A :class:`~pathlib.Path` directory that **must** exist."

NonExistentDirectory = Annotated[Path, Parameter(validator=validators.Path(file_okay=False, dir_okay=False))]
"A :class:`~pathlib.Path` directory that **must not** exist."
ResolvedDirectory = Annotated[Directory, Parameter(converter=_path_resolve_converter)]
"A :class:`~pathlib.Path` directory. :meth:`~pathlib.Path.resolve` is invoked prior to returning the path."
ResolvedExistingDirectory = Annotated[ExistingDirectory, Parameter(converter=_path_resolve_converter)]
"A :class:`~pathlib.Path` directory that **must** exist. :meth:`~pathlib.Path.resolve` is invoked prior to returning the path."

File = Annotated[Path, Parameter(validator=validators.Path(dir_okay=False))]
"A :class:`~pathlib.File` that **must** be a file (or not exist)."
ExistingFile = Annotated[Path, Parameter(validator=validators.Path(exists=True, dir_okay=False))]
"A :class:`~pathlib.Path` file that **must** exist."

NonExistentFile = Annotated[Path, Parameter(validator=validators.Path(file_okay=False, dir_okay=False))]
"A :class:`~pathlib.Path` file that **must not** exist."
ResolvedFile = Annotated[File, Parameter(converter=_path_resolve_converter)]
"A :class:`~pathlib.Path` file. :meth:`~pathlib.Path.resolve` is invoked prior to returning the path."
ResolvedExistingFile = Annotated[ExistingFile, Parameter(converter=_path_resolve_converter)]
"A :class:`~pathlib.Path` file that **must** exist. :meth:`~pathlib.Path.resolve` is invoked prior to returning the path."

# Common path extensions
BinPath = Annotated[Path, Parameter(validator=validators.Path(ext="bin", dir_okay=False))]
"A :class:`~pathlib.Path` that **must** have extension ``bin``."
ExistingBinPath = Annotated[Path, Parameter(validator=validators.Path(ext="bin", exists=True, dir_okay=False))]
"A :class:`~pathlib.Path` that **must** exist and have extension ``bin``."

NonExistentBinPath = Annotated[Path, Parameter(validator=validators.Path(ext="bin", file_okay=False, dir_okay=False))]
"A :class:`~pathlib.Path` that **must not** exist and have extension ``bin``."

CsvPath = Annotated[Path, Parameter(validator=validators.Path(ext="csv", dir_okay=False))]
"A :class:`~pathlib.Path` that **must** have extension ``csv``."
ExistingCsvPath = Annotated[Path, Parameter(validator=validators.Path(ext="csv", exists=True, dir_okay=False))]
"A :class:`~pathlib.Path` that **must** exist and have extension ``csv``."

NonExistentCsvPath = Annotated[Path, Parameter(validator=validators.Path(ext="csv", file_okay=False, dir_okay=False))]
"A :class:`~pathlib.Path` that **must not** exist and have extension ``csv``."

TxtPath = Annotated[Path, Parameter(validator=validators.Path(ext="txt", dir_okay=False))]
"A :class:`~pathlib.Path` that **must** have extension ``txt``."
ExistingTxtPath = Annotated[Path, Parameter(validator=validators.Path(ext="txt", exists=True, dir_okay=False))]
"A :class:`~pathlib.Path` that **must** exist and have extension ``txt``."

NonExistentTxtPath = Annotated[Path, Parameter(validator=validators.Path(ext="txt", file_okay=False, dir_okay=False))]
"A :class:`~pathlib.Path` that **must not** exist and have extension ``txt``."

ImagePath = Annotated[Path, Parameter(validator=validators.Path(ext=("png", "jpg", "jpeg"), dir_okay=False))]
"A :class:`~pathlib.Path` that **must** have extension in {``png``, ``jpg``, ``jpeg``}."
ExistingImagePath = Annotated[
    Path, Parameter(validator=validators.Path(ext=("png", "jpg", "jpeg"), exists=True, dir_okay=False))
]
"A :class:`~pathlib.Path` that **must** exist and have extension in {``png``, ``jpg``, ``jpeg``}."

NonExistentImagePath = Annotated[
    Path, Parameter(validator=validators.Path(ext=("png", "jpg", "jpeg"), file_okay=False, dir_okay=False))
]
"A :class:`~pathlib.Path` that **must not** exist and have extension in {``png``, ``jpg``, ``jpeg``}."

Mp4Path = Annotated[Path, Parameter(validator=validators.Path(ext="mp4", dir_okay=False))]
"A :class:`~pathlib.Path` that **must** have extension ``mp4``."
ExistingMp4Path = Annotated[Path, Parameter(validator=validators.Path(ext="mp4", exists=True, dir_okay=False))]
"A :class:`~pathlib.Path` that **must** exist and have extension ``mp4``."

NonExistentMp4Path = Annotated[Path, Parameter(validator=validators.Path(ext="mp4", file_okay=False, dir_okay=False))]
"A :class:`~pathlib.Path` that **must not** exist and have extension ``mp4``."

JsonPath = Annotated[Path, Parameter(validator=validators.Path(ext="json", dir_okay=False))]
"A :class:`~pathlib.Path` that **must** have extension ``json``."
ExistingJsonPath = Annotated[Path, Parameter(validator=validators.Path(ext="json", exists=True, dir_okay=False))]
"A :class:`~pathlib.Path` that **must** exist and have extension ``json``."

NonExistentJsonPath = Annotated[Path, Parameter(validator=validators.Path(ext="json", file_okay=False, dir_okay=False))]
"A :class:`~pathlib.Path` that **must not** exist and have extension ``json``."

TomlPath = Annotated[Path, Parameter(validator=validators.Path(ext="toml", dir_okay=False))]
"A :class:`~pathlib.Path` that **must** have extension ``toml``."
ExistingTomlPath = Annotated[Path, Parameter(validator=validators.Path(ext="toml", exists=True, dir_okay=False))]
"A :class:`~pathlib.Path` that **must** exist and have extension ``toml``."

NonExistentTomlPath = Annotated[Path, Parameter(validator=validators.Path(ext="toml", file_okay=False, dir_okay=False))]
"A :class:`~pathlib.Path` that **must not** exist and have extension ``toml``."

YamlPath = Annotated[Path, Parameter(validator=validators.Path(ext="yaml", dir_okay=False))]
"A :class:`~pathlib.Path` that **must** have extension ``yaml``."
ExistingYamlPath = Annotated[Path, Parameter(validator=validators.Path(ext="yaml", exists=True, dir_okay=False))]
"A :class:`~pathlib.Path` that **must** exist and have extension ``yaml``."

NonExistentYamlPath = Annotated[Path, Parameter(validator=validators.Path(ext="yaml", file_okay=False, dir_okay=False))]
"A :class:`~pathlib.Path` that **must not** exist and have extension ``yaml``."


##########
# Number #
##########
# foo
PositiveFloat = Annotated[float, Parameter(validator=validators.Number(gt=0))]
"A float that **must** be ``>0``."
NonNegativeFloat = Annotated[float, Parameter(validator=validators.Number(gte=0))]
"A float that **must** be ``>=0``."
NegativeFloat = Annotated[float, Parameter(validator=validators.Number(lt=0))]
"A float that **must** be ``<0``."
NonPositiveFloat = Annotated[float, Parameter(validator=validators.Number(lte=0))]
"A float that **must** be ``<=0``."

PositiveInt = Annotated[int, Parameter(validator=validators.Number(gt=0))]
"An int that **must** be ``>0``."
NonNegativeInt = Annotated[int, Parameter(validator=validators.Number(gte=0))]
"An int that **must** be ``>=0``."
NegativeInt = Annotated[int, Parameter(validator=validators.Number(lt=0))]
"An int that **must** be ``<0``."
NonPositiveInt = Annotated[int, Parameter(validator=validators.Number(lte=0))]
"An int that **must** be ``<=0``."

UInt8 = Annotated[int, Parameter(validator=validators.Number(gte=0, lte=255))]
"An unsigned 8-bit integer."
Int8 = Annotated[int, Parameter(validator=validators.Number(gte=-128, lte=127))]
"A signed 8-bit integer."

UInt16 = Annotated[int, Parameter(validator=validators.Number(gte=0, lte=65535))]
"An unsigned 16-bit integer."
Int16 = Annotated[int, Parameter(validator=validators.Number(gte=-32768, lte=32767))]
"A signed 16-bit integer."

UInt32 = Annotated[int, Parameter(validator=validators.Number(gte=0, lt=1 << 32))]
"An unsigned 32-bit integer."
Int32 = Annotated[int, Parameter(validator=validators.Number(gte=(-1 << 31), lt=(1 << 31)))]
"A signed 32-bit integer."

UInt64 = Annotated[int, Parameter(validator=validators.Number(gte=0, lt=1 << 64))]
"An unsigned 64-bit integer."
Int64 = Annotated[int, Parameter(validator=validators.Number(gte=(-1 << 63), lt=(1 << 63)))]
"A signed 64-bit integer."


def _hex_formatter(value: int, digits=0) -> str:
    return f"0x{value:X}" if digits <= 0 else f"0x{value:0{digits}X}"


HexUInt = Annotated[NonNegativeInt, Parameter(show_default=_hex_formatter)]
"A non-negative integer who's default value will be displayed as hexadecimal in the help-page."

HexUInt8 = Annotated[UInt8, Parameter(show_default=partial(_hex_formatter, digits=2))]
"An unsigned 8-bit integer who's default value will be displayed as hexadecimal in the help-page."

HexUInt16 = Annotated[UInt16, Parameter(show_default=partial(_hex_formatter, digits=4))]
"An unsigned 16-bit integer who's default value will be displayed as hexadecimal in the help-page."

HexUInt32 = Annotated[UInt32, Parameter(show_default=partial(_hex_formatter, digits=8))]
"An unsigned 32-bit integer who's default value will be displayed as hexadecimal in the help-page."

HexUInt64 = Annotated[UInt64, Parameter(show_default=partial(_hex_formatter, digits=16))]
"An unsigned 64-bit integer who's default value will be displayed as hexadecimal in the help-page."


########
# Json #
########
def _json_converter(type_, tokens: Sequence["Token"]):
    assert len(tokens) == 1
    out = json.loads(tokens[0].value)
    return out


Json = Annotated[Any, Parameter(converter=_json_converter)]
"""
Parse a json-string from the CLI.

Note: Since Cyclopts v3.6.0, all dataclass-like classes now natively attempt
to parse json-strings, so practical use-case of this annotation is limited.

Usage example:

.. code-block:: python

    from cyclopts import App, types

    app = App()

    @app.default
    def main(json: types.Json):
        print(json)

    app()

.. code-block:: console

    $ my-script '{"foo": 1, "bar": 2}'
    {'foo': 1, 'bar': 2}
"""

#######
# Web #
#######


def _email_validator(type_: Any, value: Any):
    """Simplified email validation; probably good enough for CLI usage."""
    if not isinstance(value, str):
        return

    if _email_validator.regex is None:  # pyright: ignore[reportFunctionMemberAccess]
        import re

        _email_validator.regex = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")  # pyright: ignore[reportFunctionMemberAccess]

    if not _email_validator.regex.match(value):  # pyright: ignore[reportFunctionMemberAccess]
        raise ValueError(f"Invalid email: {value}")


_email_validator.regex = None  # pyright: ignore[reportFunctionMemberAccess]

Email = Annotated[str, Parameter(validator=_email_validator)]
"An email address string with simple validation."


def _url_validator(type_: Any, value: Any):
    """Simplified URL validation; probably good enough for CLI usage."""
    if not isinstance(value, str):
        return
    if _url_validator.regex is None:  # pyright: ignore[reportFunctionMemberAccess]
        import re

        _url_validator.regex = re.compile(  # pyright: ignore[reportFunctionMemberAccess]
            r"^(?:(?:https?|ftp):\/\/)?"  # protocol
            r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+(?:[A-Z]{2,6}\.?|[A-Z0-9-]{2,}\.?)|"  # domain
            r"localhost|"  # localhost
            r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # IP
            r"(?::\d+)?"  # port
            r"(?:\/\S*)?$",  # path, query string, fragment
            re.IGNORECASE,
        )

    if not _url_validator.regex.match(value):  # pyright: ignore[reportFunctionMemberAccess]
        raise ValueError(f"Invalid URL: {value}")


_url_validator.regex = None  # pyright: ignore[reportFunctionMemberAccess]

URL = Annotated[str, Parameter(validator=_url_validator)]
"A :class:`str` URL string with some simple validation."

Port = Annotated[int, Parameter(validator=validators.Number(gte=0, lte=65535))]
"An :class:`int` limited to range ``[0, 65535]``."


def __getattr__(name: str):
    if name == "StdioPath":
        if sys.version_info < (3, 12):
            raise ImportError("StdioPath requires Python 3.12+ (Path subclassing support)")
        from cyclopts._path_type import StdioPath

        return StdioPath
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
