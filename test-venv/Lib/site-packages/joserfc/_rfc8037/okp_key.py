from __future__ import annotations

import typing as t
from functools import cached_property
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey, Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.ed448 import Ed448PublicKey, Ed448PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey, X25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x448 import X448PublicKey, X448PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    PrivateFormat,
    NoEncryption,
)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from .._rfc7517.models import CurveKey
from .._rfc7517.types import KeyParameters, AnyKey
from .._rfc7517.pem import CryptographyBinding
from ..errors import InvalidExchangeKeyError, InvalidKeyCurveError
from ..util import to_bytes, urlsafe_b64decode, urlsafe_b64encode
from ..registry import KeyParameter


LiteralCurves = t.Literal["Ed25519", "Ed448", "X25519", "X448"]
PublicOKPKey = t.Union[Ed25519PublicKey, Ed448PublicKey, X25519PublicKey, X448PublicKey]
PrivateOKPKey = t.Union[Ed25519PrivateKey, Ed448PrivateKey, X25519PrivateKey, X448PrivateKey]
OKPDictKey = t.TypedDict(
    "OKPDictKey",
    {
        "crv": LiteralCurves,
        "x": str,
        "d": str,
    },
    total=False,
)
PUBLIC_KEYS_MAP: dict[str, t.Type[PublicOKPKey]] = {
    "Ed25519": Ed25519PublicKey,
    "Ed448": Ed448PublicKey,
    "X25519": X25519PublicKey,
    "X448": X448PublicKey,
}
PRIVATE_KEYS_MAP: dict[str, t.Type[PrivateOKPKey]] = {
    "Ed25519": Ed25519PrivateKey,
    "Ed448": Ed448PrivateKey,
    "X25519": X25519PrivateKey,
    "X448": X448PrivateKey,
}
OKP_SEED_SIZES: dict[LiteralCurves, int] = {
    "Ed25519": 32,
    "Ed448": 57,
    "X25519": 32,
    "X448": 56,
}
PrivateKeyTypes = (Ed25519PrivateKey, Ed448PrivateKey, X25519PrivateKey, X448PrivateKey)


class OKPBinding(CryptographyBinding):
    key_type = "OKP"
    ssh_type = b"ssh-ed25519"
    _cryptography_key_types = (
        Ed25519PublicKey,
        Ed25519PrivateKey,
        Ed448PublicKey,
        Ed448PrivateKey,
        X25519PublicKey,
        X25519PrivateKey,
        X448PublicKey,
        X448PrivateKey,
    )

    @staticmethod
    def generate_private_key(crv: LiteralCurves) -> PrivateOKPKey:
        if crv not in PRIVATE_KEYS_MAP:
            raise InvalidKeyCurveError(f"Invalid curve value: '{crv}'")
        crv_key: t.Type[PrivateOKPKey] = PRIVATE_KEYS_MAP[crv]
        return crv_key.generate()

    @staticmethod
    def from_private_bytes(crv: LiteralCurves, data: bytes) -> PrivateOKPKey:
        crv_key: t.Type[PrivateOKPKey] = PRIVATE_KEYS_MAP[crv]
        return crv_key.from_private_bytes(data)

    @staticmethod
    def from_public_bytes(crv: LiteralCurves, data: bytes) -> PublicOKPKey:
        crv_key: t.Type[PublicOKPKey] = PUBLIC_KEYS_MAP[crv]
        return crv_key.from_public_bytes(data)

    @classmethod
    def import_private_key(cls, obj: OKPDictKey) -> PrivateOKPKey:
        d = urlsafe_b64decode(to_bytes(obj["d"]))
        return cls.from_private_bytes(obj["crv"], d)

    @classmethod
    def import_public_key(cls, obj: OKPDictKey) -> PublicOKPKey:
        x = urlsafe_b64decode(to_bytes(obj["x"]))
        return cls.from_public_bytes(obj["crv"], x)

    @classmethod
    def export_private_key(cls, key: PrivateOKPKey) -> dict[str, str]:
        obj = cls.export_public_key(key.public_key())
        d_bytes = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        obj["d"] = urlsafe_b64encode(d_bytes).decode("utf-8")
        return obj

    @classmethod
    def export_public_key(cls, key: PublicOKPKey) -> dict[str, str]:
        x_bytes = key.public_bytes(Encoding.Raw, PublicFormat.Raw)
        return {
            "crv": get_key_curve(key),
            "x": urlsafe_b64encode(x_bytes).decode("utf-8"),
        }


class OKPKey(CurveKey[PrivateOKPKey, PublicOKPKey]):
    """Key class of the ``OKP`` key type."""

    key_type = "OKP"
    #: Registry definition for OKP Key
    #: https://www.rfc-editor.org/rfc/rfc8037#section-2
    value_registry = {
        "crv": KeyParameter("Curve", "str", private=False, required=True),
        "x": KeyParameter("X Coordinate", "str", private=False, required=True),
        "d": KeyParameter("OKP Private Key", "str", private=True, required=False),
    }
    binding = OKPBinding

    def exchange_derive_key(self, key: "OKPKey") -> bytes:
        # used in ECDH-ES Algorithms
        pubkey: t.Union[X25519PublicKey, X448PublicKey] = key.get_op_key("deriveKey")  # type: ignore[assignment]

        # this if else logic is used for type hints
        if isinstance(self.private_key, X25519PrivateKey) and isinstance(pubkey, X25519PublicKey):
            return self.private_key.exchange(pubkey)
        elif isinstance(self.private_key, X448PrivateKey) and isinstance(pubkey, X448PublicKey):
            return self.private_key.exchange(pubkey)
        raise InvalidExchangeKeyError()

    @property
    def is_private(self) -> bool:
        return isinstance(self.raw_value, PrivateKeyTypes)

    @cached_property
    def public_key(self) -> PublicOKPKey:
        if isinstance(self.raw_value, PrivateKeyTypes):
            return self.raw_value.public_key()
        return self.raw_value

    @property
    def private_key(self) -> PrivateOKPKey | None:
        if isinstance(self.raw_value, PrivateKeyTypes):
            return self.raw_value
        return None

    @property
    def curve_name(self) -> LiteralCurves:
        return get_key_curve(self.raw_value)

    @classmethod
    def import_key(
        cls: t.Any,
        value: AnyKey | PrivateOKPKey | PublicOKPKey,
        parameters: KeyParameters | None = None,
        password: t.Any = None,
    ) -> "OKPKey":
        key: OKPKey
        if isinstance(
            value,
            (
                Ed25519PrivateKey,
                Ed448PrivateKey,
                X25519PrivateKey,
                X448PrivateKey,
                Ed25519PublicKey,
                Ed448PublicKey,
                X25519PublicKey,
                X448PublicKey,
            ),
        ):
            key = cls(value, value, parameters)
        else:
            key = super(OKPKey, cls).import_key(value, parameters, password)
        return key

    @classmethod
    def generate_key(
        cls: t.Type["OKPKey"],
        crv: LiteralCurves | None = "Ed25519",
        parameters: KeyParameters | None = None,
        private: bool = True,
        auto_kid: bool = False,
    ) -> "OKPKey":
        """Generate a ``OKPKey`` with the given "crv" value.

        :param crv: OKPKey curve name
        :param parameters: extra parameter in JWK
        :param private: generate a private key or public key
        :param auto_kid: add ``kid`` automatically
        """
        if crv is None:
            raw_key = cls.binding.generate_private_key("Ed25519")
        else:
            raw_key = cls.binding.generate_private_key(crv)
        return _wrap_key(cls, raw_key, private, auto_kid, parameters)

    @classmethod
    def derive_key(
        cls: t.Type["OKPKey"],
        secret: bytes | str,
        crv: LiteralCurves = "Ed25519",
        parameters: KeyParameters | None = None,
        private: bool = True,
        auto_kid: bool = False,
        kdf_name: t.Literal["HKDF", "PBKDF2"] = "HKDF",
        kdf_options: dict[str, t.Any] | None = None,
    ) -> "OKPKey":
        """
        Derives a key from a given input secret using a specified key derivation function
        (KDF) and elliptic curve algorithm.

        To derive a key using **HKDF**, the ``kdf_options`` may contain the ``algorithm``,
        ``salt`` and ``info`` values:

        .. code-block:: python

            from cryptography.hazmat.primitives import hashes
            from joserfc.jwk import OKPKey

            # default kdf_name is HKDF, algorithm is SHA256
            OKPKey.derive_key("secret")
            # equivalent to
            OKPKey.derive_key(
                "secret", "Ed25519",
                kdf_name="HKDF",
                kdf_options={
                    "algorithm": hashes.SHA256(),
                    "salt": b"joserfc:OKP:HKDF:Ed25519",
                    "info": b"",
                }
            )

        To derive a key using **PBKDF2**, the ``kdf_options`` may contain the ``algorithm``,
        ``salt`` and ``iterations`` values:

        .. code-block:: python

            from cryptography.hazmat.primitives import hashes
            from joserfc.jwk import OKPKey

            OKPKey.derive_key("secret", kdf_name="PBKDF2")
            # equivalent to
            OKPKey.derive_key(
                "secret", "Ed25519",
                kdf_name="PBKDF2",
                kdf_options={
                    "algorithm": hashes.SHA256(),
                    "salt": b"joserfc:OKP:PBKDF2:Ed25519",
                    "iterations": 100000,
                }
            )

        :param secret: The input secret used for key derivation
        :param crv: OKPKey curve name
        :param parameters: extra parameter in JWK
        :param private: generate a private key or public key
        :param auto_kid: add ``kid`` automatically
        :param kdf_name: Key derivation function name
        :param kdf_options: Additional options for the KDF
        """
        if kdf_options is None:
            kdf_options = {}

        algorithm = kdf_options.pop("algorithm", None)
        if algorithm is None:
            algorithm = hashes.SHA256()

        kdf_options.setdefault("salt", to_bytes(f"joserfc:OKP:{kdf_name}:{crv}"))
        if kdf_name == "HKDF":
            kdf_options.setdefault("info", b"")
            hkdf = HKDF(
                algorithm=algorithm,
                length=OKP_SEED_SIZES[crv],
                **kdf_options,
            )
            seed = hkdf.derive(to_bytes(secret))
        elif kdf_name == "PBKDF2":
            kdf_options.setdefault("iterations", 100000)
            pbkdf2 = PBKDF2HMAC(
                algorithm=algorithm,
                length=OKP_SEED_SIZES[crv],
                **kdf_options,
            )
            seed = pbkdf2.derive(to_bytes(secret))
        else:
            raise ValueError(f"Invalid kdf value: '{kdf_name}'")

        raw_key = cls.binding.from_private_bytes(crv, seed)
        return _wrap_key(cls, raw_key, private, auto_kid, parameters)


def get_key_curve(key: t.Union[PublicOKPKey, PrivateOKPKey]) -> LiteralCurves:
    if isinstance(key, (Ed25519PublicKey, Ed25519PrivateKey)):
        return "Ed25519"
    elif isinstance(key, (Ed448PublicKey, Ed448PrivateKey)):
        return "Ed448"
    elif isinstance(key, (X25519PublicKey, X25519PrivateKey)):
        return "X25519"
    elif isinstance(key, (X448PublicKey, X448PrivateKey)):
        return "X448"
    raise ValueError("Invalid key")  # pragma: no cover


def _wrap_key(
    cls: t.Type["OKPKey"],
    raw_key: PrivateOKPKey,
    private: bool,
    auto_kid: bool,
    parameters: KeyParameters | None = None,
) -> OKPKey:
    if private:
        key = cls(raw_key, raw_key, parameters)
    else:
        pub_key = raw_key.public_key()
        key = cls(pub_key, pub_key, parameters)
    if auto_kid:
        key.ensure_kid()
    return key
