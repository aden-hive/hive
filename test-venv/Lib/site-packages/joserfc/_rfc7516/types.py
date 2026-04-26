import typing as t

__all__ = [
    "JSONRecipientDict",
    "FlattenedJSONSerialization",
    "GeneralJSONSerialization",
]


class JSONRecipientDict(t.TypedDict, total=False):
    header: dict[str, t.Any]
    encrypted_key: str


class GeneralJSONSerialization(t.TypedDict, total=False):
    protected: str
    unprotected: dict[str, t.Any]
    iv: str
    aad: str
    ciphertext: str
    tag: str
    recipients: list[JSONRecipientDict]


class FlattenedJSONSerialization(t.TypedDict, total=False):
    protected: str
    unprotected: dict[str, t.Any]
    iv: str
    aad: str
    ciphertext: str
    tag: str
    header: dict[str, t.Any]
    encrypted_key: str
