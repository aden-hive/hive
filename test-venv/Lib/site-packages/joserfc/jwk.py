from __future__ import annotations
import typing as t
import warnings
from ._keys import (
    JWKRegistry,
    KeySet,
    Key,
    KeySetSerialization,
)
from ._rfc7517.pem import import_from_pem_key, import_from_ssh_key
from ._rfc7517.types import AnyKey, DictKey, KeyParameters
from ._rfc7518.oct_key import OctKey
from ._rfc7518.rsa_key import RSAKey
from ._rfc7518.ec_key import ECKey
from ._rfc8037.okp_key import OKPKey
from ._rfc8812 import register_secp256k1
from ._rfc7638 import calculate_thumbprint as thumbprint
from ._rfc9278 import calculate_thumbprint_uri as thumbprint_uri
from .errors import SecurityWarning, InvalidKeyTypeError
from .registry import Header
from .util import to_bytes


__all__ = [
    # types
    "Key",
    "DictKey",
    "KeyParameters",
    "KeyCallable",
    "KeyFlexible",
    "KeySetSerialization",
    "KeyBase",
    "GuestProtocol",
    # modules
    "JWKRegistry",
    "OctKey",
    "RSAKey",
    "ECKey",
    "OKPKey",
    "KeySet",
    # methods
    "guess_key",
    "import_key",
    "generate_key",
    "thumbprint",
    "thumbprint_uri",
]

register_secp256k1()


class GuestProtocol(t.Protocol):  # pragma: no cover
    def headers(self) -> Header: ...

    def set_kid(self, kid: str) -> None: ...


KeyBase = t.Union[Key, KeySet]
KeyCallable = t.Callable[[GuestProtocol], KeyBase]
KeyFlexible = t.Union[KeyBase, KeyCallable]


def guess_key(
    key: KeyFlexible,
    obj: GuestProtocol,
    random: bool = False,
    use: t.Literal["sig", "enc"] | None = None,
) -> Key:
    """Guess key from a various sources.

    :param key: a very flexible key
    :param obj: a protocol that has ``headers`` and ``set_kid`` methods
    :param random: pick a random key from key set
    :param use: optional "use" value
    """
    resolved_key: KeyBase
    if callable(key):
        resolved_key = key(obj)
    else:
        resolved_key = key

    if isinstance(resolved_key, (OctKey, RSAKey, ECKey, OKPKey)):
        return resolved_key
    elif isinstance(resolved_key, KeySet):
        headers = obj.headers()
        kid: str | None = headers.get("kid")

        parameters: KeyParameters = {"alg": headers["alg"]}
        if use:
            parameters["use"] = use

        if not kid and random:
            # choose one key by random
            return_key = resolved_key.pick_random_key(headers["alg"], parameters)
            if return_key is None:
                raise ValueError("Invalid key")
            return_key.ensure_kid()
            obj.set_kid(t.cast(str, return_key.kid))
        else:
            return_key = resolved_key.get_by_kid(kid, parameters)
        return return_key
    else:
        raise ValueError("Invalid key")


@t.overload
def import_key(data: AnyKey, key_type: t.Literal["oct"], parameters: KeyParameters | None = None) -> OctKey: ...


@t.overload
def import_key(data: AnyKey, key_type: t.Literal["RSA"], parameters: KeyParameters | None = None) -> RSAKey: ...


@t.overload
def import_key(data: AnyKey, key_type: t.Literal["EC"], parameters: KeyParameters | None = None) -> ECKey: ...


@t.overload
def import_key(data: AnyKey, key_type: t.Literal["OKP"], parameters: KeyParameters | None = None) -> OKPKey: ...


@t.overload
def import_key(data: AnyKey, key_type: None = None, parameters: KeyParameters | None = None) -> Key: ...


def import_key(
    data: AnyKey,
    key_type: t.Literal["oct", "RSA", "EC", "OKP"] | None = None,
    parameters: KeyParameters | None = None,
) -> Key:
    """Importing a key from bytes, string, and dict. When ``value`` is a dict,
    this method can tell the key type automatically, otherwise, developers
    SHOULD pass the ``key_type`` themselves.

    :param data: the key data in bytes, string, or dict.
    :param key_type: an optional key type in string.
    :param parameters: extra key parameters
    :return: OctKey, RSAKey, ECKey, or OKPKey
    """
    if isinstance(data, (str, bytes)) and key_type is None:
        warnings.warn("Using implicit key type is not recommended.", SecurityWarning)

        value = to_bytes(data)
        ssh_types = tuple(
            cls.binding.ssh_type for cls in JWKRegistry.key_types.values() if hasattr(cls.binding, "ssh_type")
        )
        if value.startswith(ssh_types):
            try:
                raw_key = import_from_ssh_key(value)
            except ValueError:
                return OctKey.import_key(value, parameters)
        else:
            try:
                raw_key = import_from_pem_key(value)
            except ValueError:
                return OctKey.import_key(value, parameters)

        for cls in JWKRegistry.key_types.values():
            if hasattr(cls.binding, "check_cryptography_key") and cls.binding.check_cryptography_key(raw_key):
                return cls(raw_key, data, parameters)
        raise InvalidKeyTypeError("Not a key of any supported type")  # pragma: no cover
    return JWKRegistry.import_key(data, key_type, parameters)


@t.overload
def generate_key(
    key_type: t.Literal["oct"],
    crv_or_size: int | None = None,
    parameters: KeyParameters | None = None,
    private: bool = True,
    auto_kid: bool = False,
) -> OctKey: ...


@t.overload
def generate_key(
    key_type: t.Literal["RSA"],
    crv_or_size: int | None = None,
    parameters: KeyParameters | None = None,
    private: bool = True,
    auto_kid: bool = False,
) -> RSAKey: ...


@t.overload
def generate_key(
    key_type: t.Literal["EC"],
    crv_or_size: t.Literal["P-256", "P-384", "P-521", "secp256k1"] | None = None,
    parameters: KeyParameters | None = None,
    private: bool = True,
    auto_kid: bool = False,
) -> ECKey: ...


@t.overload
def generate_key(
    key_type: t.Literal["OKP"],
    crv_or_size: t.Literal["Ed25519", "Ed448", "X25519", "X448"] | None = None,
    parameters: KeyParameters | None = None,
    private: bool = True,
    auto_kid: bool = False,
) -> OKPKey: ...


def generate_key(
    key_type: t.Literal["oct", "RSA", "EC", "OKP"],
    crv_or_size: str | int | None = None,
    parameters: KeyParameters | None = None,
    private: bool = True,
    auto_kid: bool = False,
) -> Key:
    """Generating key according to the given key type. When ``key_type`` is
    "oct" and "RSA", the second parameter SHOULD be a key size in bits.
    When ``key_type`` is "EC" and "OKP", the second
    parameter SHOULD be a "crv" string.
    """
    return JWKRegistry.generate_key(key_type, crv_or_size, parameters, private, auto_kid)
