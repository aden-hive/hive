from __future__ import annotations
import json
from json import JSONEncoder, JSONDecoder
from typing import Type
from ._rfc7519.claims import (
    convert_claims,
    Claims,
    ClaimsOption,
    BaseClaimsRegistry,
    JWTClaimsRegistry,
)
from ._rfc7519.security import check_sensitive_data
from .jws import (
    JWSRegistry,
    serialize_compact,
    deserialize_compact,
)
from .jwe import (
    JWERegistry,
    encrypt_compact,
    decrypt_compact,
)
from .jwk import KeyFlexible
from .errors import InvalidPayloadError
from .util import to_bytes
from .registry import Header

__all__ = [
    # types
    "Claims",
    "ClaimsOption",
    # modules
    "BaseClaimsRegistry",
    "JWTClaimsRegistry",
    "Token",
    # methods
    "encode",
    "decode",
    "check_sensitive_data",
]


class Token:
    """The extracted token object, which contains ``header`` and ``claims``.

    :param header: the header part of the JWT
    :param claims: the payload part of the JWT
    """

    def __init__(self, header: Header, claims: Claims):
        #: header in dict
        self.header = header
        #: payload claims in dict
        self.claims = claims


def encode(
    header: Header,
    claims: Claims,
    key: KeyFlexible,
    algorithms: list[str] | None = None,
    registry: JWSRegistry | JWERegistry | None = None,
    encoder_cls: Type[JSONEncoder] | None = None,
    default_type: str | None = "JWT",
) -> str:
    """Encode a JSON Web Token with the given header, and claims.

    :param header: A dict of the JWT header
    :param claims: A dict of the JWT claims to be encoded
    :param key: key used to sign the signature
    :param algorithms: a list of allowed algorithms
    :param registry: a ``JWSRegistry`` or ``JWERegistry`` to use
    :param encoder_cls: A JSONEncoder subclass to use
    :param default_type: default value of the ``typ`` header parameter
    """
    if default_type is not None:
        _header = {"typ": default_type, **header}
    else:
        _header = {**header}
    payload = convert_claims(claims, encoder_cls)
    if isinstance(registry, JWERegistry):
        return encrypt_compact(_header, payload, key, algorithms, registry)
    else:
        return serialize_compact(_header, payload, key, algorithms, registry)


def decode(
    value: bytes | str,
    key: KeyFlexible,
    algorithms: list[str] | None = None,
    registry: JWSRegistry | JWERegistry | None = None,
    decoder_cls: Type[JSONDecoder] | None = None,
) -> Token:
    """Decode the JSON Web Token string with the given key, and validate
    it with the claims requests.

    :param value: text of the JWT
    :param key: key used to verify the signature
    :param algorithms: a list of allowed algorithms
    :param registry: a ``JWSRegistry`` or ``JWERegistry`` to use
    :param decoder_cls: A JSONDecoder subclass to use
    :raise BadSignatureError: when signature verification fails
    :raise InvalidPayloadError: when payload is not a valid JSON object
    """
    _value = to_bytes(value)
    header: Header
    payload: bytes
    if isinstance(registry, JWERegistry):
        header, payload = _decode_jwe(_value, key, algorithms, registry)
    else:
        header, payload = _decode_jws(_value, key, algorithms, registry)

    try:
        claims: Claims = json.loads(payload, cls=decoder_cls)
    except (TypeError, ValueError):
        raise InvalidPayloadError()

    return Token(header, claims)


def _decode_jwe(
    value: bytes, key: KeyFlexible, algorithms: list[str] | None = None, registry: JWERegistry | None = None
) -> tuple[Header, bytes]:
    jwe_obj = decrypt_compact(value, key, algorithms, registry)
    assert jwe_obj.plaintext is not None
    return jwe_obj.headers(), jwe_obj.plaintext


def _decode_jws(
    value: bytes, key: KeyFlexible, algorithms: list[str] | None = None, registry: JWSRegistry | None = None
) -> tuple[Header, bytes]:
    jws_obj = deserialize_compact(value, key, algorithms, registry)
    assert jws_obj.payload is not None
    return jws_obj.headers(), jws_obj.payload
