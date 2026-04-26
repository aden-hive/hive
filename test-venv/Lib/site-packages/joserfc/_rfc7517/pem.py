from __future__ import annotations
from typing import Any, Literal, cast
from abc import ABCMeta, abstractmethod
from cryptography.x509 import load_pem_x509_certificate
from cryptography.hazmat.primitives.serialization import (
    load_pem_private_key,
    load_pem_public_key,
    load_ssh_public_key,
    load_ssh_private_key,
    load_der_private_key,
    load_der_public_key,
    Encoding,
    PrivateFormat,
    PublicFormat,
    KeySerializationEncryption,
    BestAvailableEncryption,
    NoEncryption,
)
from .models import NativeKeyBinding, GenericKey
from .types import DictKey
from ..errors import InvalidKeyTypeError
from ..util import to_bytes


def import_from_ssh_key(raw: bytes) -> Any:
    return load_ssh_public_key(raw)


def import_from_pem_key(raw: bytes, password: bytes | None = None) -> Any:
    key: Any

    if b"OPENSSH PRIVATE" in raw:
        key = load_ssh_private_key(raw, password=password)

    elif b"PUBLIC" in raw:
        key = load_pem_public_key(raw)

    elif b"PRIVATE" in raw:
        key = load_pem_private_key(raw, password=password)

    elif b"CERTIFICATE" in raw:
        cert = load_pem_x509_certificate(raw)
        return cert.public_key()

    else:
        try:
            key = load_der_private_key(raw, password=password)
        except ValueError:
            key = load_der_public_key(raw)
    return key


def dump_pem_key(
    key: Any,
    encoding: Literal["PEM", "DER"] | None = None,
    private: bool | None = False,
    password: Any | None = None,
) -> bytes:
    """Export key into PEM/DER format bytes.

    :param key: native cryptography key
    :param encoding: "PEM" or "DER"
    :param private: export private key or public key
    :param password: encrypt private key with password
    :return: bytes
    """

    if encoding is None or encoding == "PEM":
        encoding_enum = Encoding.PEM
    elif encoding == "DER":
        encoding_enum = Encoding.DER
    else:  # pragma: no cover
        raise ValueError(f"Invalid encoding: {encoding}")

    if private:
        encryption_algorithm: KeySerializationEncryption
        if password is None:
            encryption_algorithm = NoEncryption()
        else:
            encryption_algorithm = BestAvailableEncryption(to_bytes(password))
        value = key.private_bytes(
            encoding=encoding_enum,
            format=PrivateFormat.PKCS8,
            encryption_algorithm=encryption_algorithm,
        )
    else:
        value = key.public_bytes(
            encoding=encoding_enum,
            format=PublicFormat.SubjectPublicKeyInfo,
        )
    return cast(bytes, value)


class CryptographyBinding(NativeKeyBinding, metaclass=ABCMeta):
    key_type: str
    ssh_type: bytes
    _cryptography_key_types: Any

    @classmethod
    def check_ssh_type(cls, value: bytes) -> bool:
        return value.startswith(cls.ssh_type)

    @classmethod
    def check_cryptography_key(cls, native_key: Any) -> bool:
        return isinstance(native_key, cls._cryptography_key_types)

    @classmethod
    def convert_raw_key_to_dict(cls, raw_key: Any, private: bool) -> DictKey:
        if private:
            value = cls.export_private_key(raw_key)
        else:
            value = cls.export_public_key(raw_key)
        return cast(DictKey, value)

    @classmethod
    def import_from_dict(cls, value: DictKey) -> Any:
        if "d" in value:
            return cls.import_private_key(value)
        return cls.import_public_key(value)

    @classmethod
    def import_from_bytes(cls, value: bytes, password: Any | None = None) -> Any:
        if cls.check_ssh_type(value):
            return import_from_ssh_key(value)

        if password is not None:
            password = to_bytes(password)

        key = import_from_pem_key(value, password)
        if not cls.check_cryptography_key(key):
            raise InvalidKeyTypeError(f"Not a key of: '{cls.key_type}'")
        return key

    @staticmethod
    def as_bytes(
        key: GenericKey,
        encoding: Literal["PEM", "DER"] | None = None,
        private: bool | None = False,
        password: Any | None = None,
    ) -> bytes:
        if private is None:
            private = key.is_private

        if private:
            return dump_pem_key(key.private_key, encoding, private, password)
        else:
            return dump_pem_key(key.public_key, encoding, private, password)

    @classmethod
    @abstractmethod
    def import_private_key(cls, obj: Any) -> Any:
        pass

    @classmethod
    @abstractmethod
    def import_public_key(cls, obj: Any) -> Any:
        pass

    @classmethod
    @abstractmethod
    def export_private_key(cls, key: Any) -> Any:
        pass

    @classmethod
    @abstractmethod
    def export_public_key(cls, key: Any) -> Any:
        pass
