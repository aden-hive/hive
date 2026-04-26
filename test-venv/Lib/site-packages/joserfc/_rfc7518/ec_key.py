from __future__ import annotations

import typing as t
from functools import cached_property
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.ec import (
    generate_private_key,
    derive_private_key,
    ECDH,
    EllipticCurvePublicKey,
    EllipticCurvePrivateKey,
    EllipticCurvePrivateNumbers,
    EllipticCurvePublicNumbers,
    EllipticCurve,
    SECP256R1,
    SECP384R1,
    SECP521R1,
)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from ..errors import InvalidExchangeKeyError, InvalidKeyCurveError
from .._rfc7517.models import CurveKey
from .._rfc7517.pem import CryptographyBinding
from .._rfc7517.types import KeyParameters, AnyKey
from ..util import base64_to_int, int_to_base64, to_bytes
from ..registry import KeyParameter

__all__ = ["ECKey"]

ECDictKey = t.TypedDict(
    "ECDictKey",
    {
        "crv": str,
        "x": str,
        "y": str,
        "d": str,  # optional
    },
    total=False,
)


class ECBinding(CryptographyBinding):
    key_type = "EC"
    ssh_type = b"ecdsa-sha2-"
    _cryptography_key_types = (EllipticCurvePrivateKey, EllipticCurvePublicKey)

    _dss_curves: dict[str, t.Type[EllipticCurve]] = {}
    _curves_dss: dict[str, str] = {}

    @classmethod
    def register_curve(cls, name: str, curve: t.Type[EllipticCurve]) -> None:
        cls._dss_curves[name] = curve
        cls._curves_dss[str(curve.name)] = name

    @classmethod
    def generate_private_key(cls, name: str) -> EllipticCurvePrivateKey:
        if name not in cls._dss_curves:
            raise InvalidKeyCurveError(f"Invalid crv value: '{name}'")

        curve = cls._dss_curves[name]()
        return generate_private_key(curve=curve)

    @classmethod
    def import_private_key(cls, obj: ECDictKey) -> EllipticCurvePrivateKey:
        curve = cls._dss_curves[obj["crv"]]()
        public_numbers = EllipticCurvePublicNumbers(
            base64_to_int(obj["x"]),
            base64_to_int(obj["y"]),
            curve,
        )
        d = base64_to_int(obj["d"])
        private_numbers = EllipticCurvePrivateNumbers(d, public_numbers)
        return private_numbers.private_key()

    @classmethod
    def export_private_key(cls, key: EllipticCurvePrivateKey) -> ECDictKey:
        numbers = key.private_numbers()
        byte_count = (key.key_size + 7) // 8
        return {
            "crv": cls._curves_dss[key.curve.name],
            "x": int_to_base64(numbers.public_numbers.x, byte_count),
            "y": int_to_base64(numbers.public_numbers.y, byte_count),
            "d": int_to_base64(numbers.private_value, byte_count),
        }

    @classmethod
    def import_public_key(cls, obj: ECDictKey) -> EllipticCurvePublicKey:
        curve = cls._dss_curves[obj["crv"]]()
        public_numbers = EllipticCurvePublicNumbers(
            base64_to_int(obj["x"]),
            base64_to_int(obj["y"]),
            curve,
        )
        return public_numbers.public_key()

    @classmethod
    def export_public_key(cls, key: EllipticCurvePublicKey) -> ECDictKey:
        numbers = key.public_numbers()
        byte_count = (key.key_size + 7) // 8
        return {
            "crv": cls._curves_dss[numbers.curve.name],
            "x": int_to_base64(numbers.x, byte_count),
            "y": int_to_base64(numbers.y, byte_count),
        }


# register default curves with their DSS (Digital Signature Standard) names
# https://nvlpubs.nist.gov/nistpubs/FIPS/NIST.FIPS.186-4.pdf
ECBinding.register_curve("P-256", SECP256R1)
ECBinding.register_curve("P-384", SECP384R1)
ECBinding.register_curve("P-521", SECP521R1)


class ECKey(CurveKey[EllipticCurvePrivateKey, EllipticCurvePublicKey]):
    key_type = "EC"
    #: Registry definition for EC Key
    #: https://www.rfc-editor.org/rfc/rfc7518#section-6.2
    value_registry = {
        "crv": KeyParameter("Curve", "str", private=False, required=True),
        "x": KeyParameter("X Coordinate", "str", private=False, required=True),
        "y": KeyParameter("Y Coordinate", "str", private=False, required=True),
        "d": KeyParameter("EC Private Key", "str", private=True, required=False),
    }
    binding = ECBinding

    @property
    def is_private(self) -> bool:
        return isinstance(self.raw_value, EllipticCurvePrivateKey)

    @cached_property
    def public_key(self) -> EllipticCurvePublicKey:
        if isinstance(self.raw_value, EllipticCurvePrivateKey):
            return self.raw_value.public_key()
        return self.raw_value

    @property
    def private_key(self) -> EllipticCurvePrivateKey | None:
        if isinstance(self.raw_value, EllipticCurvePrivateKey):
            return self.raw_value
        return None

    def exchange_derive_key(self, key: "ECKey") -> bytes:
        pubkey = key.get_op_key("deriveKey")
        if self.private_key and self.curve_name == key.curve_name:
            return self.private_key.exchange(ECDH(), pubkey)
        raise InvalidExchangeKeyError()

    @property
    def curve_name(self) -> str:
        return self.binding._curves_dss[self.raw_value.curve.name]

    @property
    def curve_key_size(self) -> int:
        return self.raw_value.curve.key_size

    @classmethod
    def import_key(
        cls: t.Any,
        value: AnyKey | EllipticCurvePrivateKey | EllipticCurvePublicKey,
        parameters: KeyParameters | None = None,
        password: t.Any = None,
    ) -> "ECKey":
        key: ECKey
        if isinstance(value, (EllipticCurvePrivateKey, EllipticCurvePublicKey)):
            key = cls(value, value, parameters)
        else:
            key = super(ECKey, cls).import_key(value, parameters, password)
        return key

    @classmethod
    def generate_key(
        cls: t.Type["ECKey"],
        crv: str | None = "P-256",
        parameters: KeyParameters | None = None,
        private: bool = True,
        auto_kid: bool = False,
    ) -> "ECKey":
        """Generate a ``ECKey`` with the given "crv" value.

        :param crv: ECKey curve name
        :param parameters: extra parameter in JWK
        :param private: generate a private key or public key
        :param auto_kid: add ``kid`` automatically
        """
        if crv is None:
            crv = "P-256"
        raw_key = cls.binding.generate_private_key(crv)
        return _wrap_key(cls, raw_key, private, auto_kid, parameters)

    @classmethod
    def derive_key(
        cls: t.Type["ECKey"],
        secret: bytes | str,
        crv: str = "P-256",
        parameters: KeyParameters | None = None,
        private: bool = True,
        auto_kid: bool = False,
        kdf_name: t.Literal["HKDF", "PBKDF2"] = "HKDF",
        kdf_options: dict[str, t.Any] | None = None,
    ) -> "ECKey":
        """
        Generate an elliptic curve cryptographic key derived from a secret input using a key
        derivation function (KDF). This allows the creation of deterministic elliptic curve
        keys based on given input data, curve specification, and KDF options.

        :param secret: The input secret used for key derivation
        :param crv: ECKey curve name
        :param parameters: extra parameter in JWK
        :param private: generate a private key or public key
        :param auto_kid: add ``kid`` automatically
        :param kdf_name: Key derivation function name
        :param kdf_options: Additional options for the KDF
        """
        try:
            curve_class = cls.binding._dss_curves[crv]
        except KeyError:
            raise InvalidKeyCurveError(f"Invalid crv value: '{crv}'")

        curve = curve_class()
        length = (curve.group_order.bit_length() + 7) // 8 * 2

        if kdf_options is None:
            kdf_options = {}

        algorithm = kdf_options.pop("algorithm", None)
        if algorithm is None:
            algorithm = hashes.SHA256()

        kdf_options.setdefault("salt", to_bytes(f"joserfc:EC:{kdf_name}:{crv}"))
        if kdf_name == "HKDF":
            kdf_options.setdefault("info", b"")
            hkdf = HKDF(
                algorithm=algorithm,
                length=length,
                **kdf_options,
            )
            seed = hkdf.derive(to_bytes(secret))
        elif kdf_name == "PBKDF2":
            kdf_options.setdefault("iterations", 100000)
            pbkdf2 = PBKDF2HMAC(
                algorithm=algorithm,
                length=length,
                **kdf_options,
            )
            seed = pbkdf2.derive(to_bytes(secret))
        else:
            raise ValueError(f"Invalid kdf value: '{kdf_name}'")

        d = int.from_bytes(seed, "big") % curve.group_order
        raw_key = derive_private_key(d, curve)
        return _wrap_key(cls, raw_key, private, auto_kid, parameters)


def _wrap_key(
    cls: t.Type["ECKey"],
    raw_key: EllipticCurvePrivateKey,
    private: bool,
    auto_kid: bool,
    parameters: KeyParameters | None = None,
) -> ECKey:
    if private:
        key = cls(raw_key, raw_key, parameters)
    else:
        pub_key = raw_key.public_key()
        key = cls(pub_key, pub_key, parameters)
    if auto_kid:
        key.ensure_kid()
    return key
