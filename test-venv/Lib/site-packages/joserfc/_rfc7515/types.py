import typing as t
from ..registry import Header

__all__ = [
    "SegmentsDict",
    "HeaderDict",
    "JSONSignatureDict",
    "GeneralJSONSerialization",
    "FlattenedJSONSerialization",
]


class SegmentsDict(t.TypedDict, total=False):
    header: bytes
    payload: bytes
    signature: bytes


class HeaderDict(t.TypedDict, total=False):
    protected: Header
    header: Header


class JSONSignatureDict(t.TypedDict, total=False):
    protected: str
    header: Header
    signature: str


@t.final
class GeneralJSONSerialization(t.TypedDict):
    payload: str
    signatures: list[JSONSignatureDict]


@t.final
class FlattenedJSONSerialization(t.TypedDict, total=False):
    payload: str
    protected: str
    header: Header
    signature: str
