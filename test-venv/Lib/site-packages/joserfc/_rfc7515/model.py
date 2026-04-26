from __future__ import annotations
from typing import Any, ClassVar, Literal
from abc import ABCMeta, abstractmethod
from .types import SegmentsDict, JSONSignatureDict
from ..errors import InvalidKeyTypeError
from ..registry import Header

__all__ = [
    "HeaderMember",
    "CompactSignature",
    "FlattenedJSONSignature",
    "GeneralJSONSignature",
    "JWSAlgModel",
]


class HeaderMember:
    """A header member of the JSON signature. It is combined with protected header,
    and unprotected header.
    """

    def __init__(self, protected: Header | None = None, header: Header | None = None):
        #: protected header
        self.protected = protected
        #: unprotected header
        self.header = header

    def headers(self) -> Header:
        rv: Header = {}
        if self.header:
            rv.update(self.header)

        # protected header is preferred
        if self.protected:
            rv.update(self.protected)
        return rv

    def set_kid(self, kid: str) -> None:
        if self.header is None:
            self.header = {}
        self.header["kid"] = kid


class CompactSignature:
    """JSON Web Signature object for compact mode. This object is used to
    represent the JWS instance.
    """

    def __init__(self, protected: Header, payload: bytes):
        #: protected header
        self.protected = protected
        #: payload content in bytes
        self.payload = payload
        self.segments: SegmentsDict = {}

    def headers(self) -> Header:
        """Returns protected header values in dict."""
        return self.protected

    def set_kid(self, kid: str) -> None:
        self.protected["kid"] = kid


class FlattenedJSONSignature:
    """JSON Signature object that represents a flattened JSON serialization."""

    #: mark it as flattened
    flattened: ClassVar[bool] = True

    def __init__(self, member: HeaderMember, payload: bytes):
        #: the only header member
        self.member: HeaderMember = member
        #: payload content in bytes
        self.payload: bytes = payload
        self.signature: JSONSignatureDict | None = None
        self.segments: SegmentsDict = {}

    @property
    def members(self) -> list[HeaderMember]:
        """A list of header members. For flattened JSON serialization, there will
        be only one header member."""
        return [self.member]

    def headers(self) -> Header:
        """Header values in dict."""
        return self.member.headers()


class GeneralJSONSignature:
    """JSON Signature object that represents a general JSON serialization."""

    #: mark it as not flattened (general)
    flattened: ClassVar[bool] = False

    def __init__(self, members: list[HeaderMember], payload: bytes):
        #: a list of header members
        self.members: list[HeaderMember] = members
        #: payload content in bytes
        self.payload: bytes = payload
        self.signatures: list[JSONSignatureDict] = []
        self.segments: SegmentsDict = {}


class JWSAlgModel(metaclass=ABCMeta):
    """Interface for JWS algorithm. JWA specification (RFC7518) SHOULD
    implement the algorithms for JWS with this base implementation.
    """

    name: str
    description: str
    recommended: bool = False
    security_warning: str | None = None

    key_type = "oct"
    algorithm_type: Literal["JWS"] = "JWS"
    algorithm_location = "sig"
    algorithm_security = 0

    def check_key(self, key: Any) -> None:
        key.check_use("sig")
        if key.key_type != self.key_type:
            raise InvalidKeyTypeError(f"Algorithm '{self.name}' requires '{self.key_type}' key")
        key.check_alg(self.name)

    @abstractmethod
    def sign(self, msg: bytes, key: Any) -> bytes:
        """Sign the text msg with a private/sign key.

        :param msg: message bytes to be signed
        :param key: private key to sign the message
        :return: bytes
        """

    @abstractmethod
    def verify(self, msg: bytes, sig: bytes, key: Any) -> bool:
        """Verify the signature of text msg with a public/verify key.

        :param msg: message bytes to be signed
        :param sig: result signature to be compared
        :param key: public key to verify the signature
        :return: boolean
        """
