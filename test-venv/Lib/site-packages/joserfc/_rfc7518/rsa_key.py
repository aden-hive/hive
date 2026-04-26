from __future__ import annotations
import warnings
import typing as t
from functools import cached_property
from cryptography.hazmat.primitives.asymmetric.rsa import (
    generate_private_key,
    RSAPublicKey,
    RSAPrivateKey,
    RSAPrivateNumbers,
    RSAPublicNumbers,
    rsa_recover_prime_factors,
    rsa_crt_dmp1,
    rsa_crt_dmq1,
    rsa_crt_iqmp,
)
from ..registry import KeyParameter
from ..errors import SecurityWarning, KeyParameterError
from .._rfc7517.models import AsymmetricKey
from .._rfc7517.pem import CryptographyBinding
from .._rfc7517.types import KeyParameters, AnyKey
from ..util import int_to_base64, base64_to_int


RSADictKey = t.TypedDict(
    "RSADictKey",
    {
        "n": str,
        "e": str,
        "d": str,
        "p": str,
        "q": str,
        "dp": str,
        "dq": str,
        "qi": str,
    },
    total=False,
)


class RSABinding(CryptographyBinding):
    key_type = "RSA"
    ssh_type = b"ssh-rsa"
    _cryptography_key_types = (RSAPrivateKey, RSAPublicKey)

    @staticmethod
    def generate_private_key(size: int) -> RSAPrivateKey:
        return generate_private_key(public_exponent=65537, key_size=size)

    @classmethod
    def import_private_key(cls, obj: RSADictKey) -> RSAPrivateKey:
        if "oth" in obj:  # pragma: no cover
            # https://tools.ietf.org/html/rfc7518#section-6.3.2.7
            raise ValueError('"oth" is not supported yet')

        public_numbers = RSAPublicNumbers(base64_to_int(obj["e"]), base64_to_int(obj["n"]))

        if has_all_prime_factors(obj):
            numbers = RSAPrivateNumbers(
                d=base64_to_int(obj["d"]),
                p=base64_to_int(obj["p"]),
                q=base64_to_int(obj["q"]),
                dmp1=base64_to_int(obj["dp"]),
                dmq1=base64_to_int(obj["dq"]),
                iqmp=base64_to_int(obj["qi"]),
                public_numbers=public_numbers,
            )
        else:
            d = base64_to_int(obj["d"])
            p, q = rsa_recover_prime_factors(public_numbers.n, d, public_numbers.e)
            numbers = RSAPrivateNumbers(
                d=d,
                p=p,
                q=q,
                dmp1=rsa_crt_dmp1(d, p),
                dmq1=rsa_crt_dmq1(d, q),
                iqmp=rsa_crt_iqmp(p, q),
                public_numbers=public_numbers,
            )

        return numbers.private_key()

    @classmethod
    def export_private_key(cls, key: RSAPrivateKey) -> RSADictKey:
        numbers = key.private_numbers()
        return {
            "n": int_to_base64(numbers.public_numbers.n),
            "e": int_to_base64(numbers.public_numbers.e),
            "d": int_to_base64(numbers.d),
            "p": int_to_base64(numbers.p),
            "q": int_to_base64(numbers.q),
            "dp": int_to_base64(numbers.dmp1),
            "dq": int_to_base64(numbers.dmq1),
            "qi": int_to_base64(numbers.iqmp),
        }

    @classmethod
    def import_public_key(cls, obj: RSADictKey) -> RSAPublicKey:
        numbers = RSAPublicNumbers(base64_to_int(obj["e"]), base64_to_int(obj["n"]))
        return numbers.public_key()

    @classmethod
    def export_public_key(cls, key: RSAPublicKey) -> dict[str, str]:
        numbers = key.public_numbers()
        return {"n": int_to_base64(numbers.n), "e": int_to_base64(numbers.e)}


class RSAKey(AsymmetricKey[RSAPrivateKey, RSAPublicKey]):
    key_type = "RSA"
    #: Registry definition for RSA Key
    #: https://www.rfc-editor.org/rfc/rfc7518#section-6.3
    value_registry = {
        "n": KeyParameter("Modulus", "str", private=False, required=True),
        "e": KeyParameter("Exponent", "str", private=False, required=True),
        "d": KeyParameter("Private Exponent", "str", private=True, required=False),
        "p": KeyParameter("First Prime Factor", "str", private=True, required=False),
        "q": KeyParameter("Second Prime Factor", "str", private=True, required=False),
        "dp": KeyParameter("First Factor CRT Exponent", "str", private=True, required=False),
        "dq": KeyParameter("Second Factor CRT Exponent", "str", private=True, required=False),
        "qi": KeyParameter("First CRT Coefficient", "str", private=True, required=False),
        "oth": KeyParameter("Other Primes Info", "none", private=True, required=False),
    }
    binding = RSABinding

    @property
    def is_private(self) -> bool:
        return isinstance(self.raw_value, RSAPrivateKey)

    @cached_property
    def public_key(self) -> RSAPublicKey:
        if isinstance(self.raw_value, RSAPrivateKey):
            return self.raw_value.public_key()
        return self.raw_value

    @property
    def private_key(self) -> RSAPrivateKey | None:
        if isinstance(self.raw_value, RSAPrivateKey):
            return self.raw_value
        return None

    @classmethod
    def import_key(
        cls: t.Any,
        value: AnyKey | RSAPrivateKey | RSAPublicKey,
        parameters: KeyParameters | None = None,
        password: t.Any = None,
    ) -> "RSAKey":
        key: RSAKey
        if isinstance(value, (RSAPrivateKey, RSAPublicKey)):
            key = cls(value, value, parameters)
        else:
            key = super(RSAKey, cls).import_key(value, parameters, password)
        if key.raw_value.key_size < 2048:
            # https://csrc.nist.gov/publications/detail/sp/800-131a/rev-2/final
            warnings.warn("Key size should be >= 2048 bits", SecurityWarning)
        return key

    @classmethod
    def generate_key(
        cls: t.Type["RSAKey"],
        key_size: int | None = 2048,
        parameters: KeyParameters | None = None,
        private: bool = True,
        auto_kid: bool = False,
    ) -> "RSAKey":
        """Generate a ``RSAKey`` with the given bit size (not bytes).

        :param key_size: size in bit
        :param parameters: extra parameter in JWK
        :param private: generate a private key or public key
        :param auto_kid: add ``kid`` automatically
        """
        if key_size is None:
            key_size = 2048

        if key_size % 8 != 0:
            raise ValueError("A bit size must be a multiple of 8")

        if key_size < 2048:
            # https://csrc.nist.gov/publications/detail/sp/800-131a/rev-2/final
            warnings.warn("Key size should be >= 2048 bits", SecurityWarning)

        raw_key = cls.binding.generate_private_key(key_size)
        if private:
            key = cls(raw_key, raw_key, parameters)
        else:
            pub_key = raw_key.public_key()
            key = cls(pub_key, pub_key, parameters)
        if auto_kid:
            key.ensure_kid()
        return key


def has_all_prime_factors(obj: RSADictKey) -> bool:
    props = ["p", "q", "dp", "dq", "qi"]
    props_found = [prop in obj for prop in props]
    if all(props_found):
        return True

    if any(props_found):
        raise KeyParameterError("RSA key must include all parameters if any are present besides d")

    return False
