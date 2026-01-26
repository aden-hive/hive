from cryptography.fernet import Fernet, MultiFernet
from key_value.shared.errors.wrappers.encryption import EncryptionVersionError
from typing_extensions import overload

from key_value.aio.protocols.key_value import AsyncKeyValue
from key_value.aio.wrappers.encryption.base import BaseEncryptionWrapper

ENCRYPTION_VERSION = 1

KDF_ITERATIONS = 1_200_000


class FernetEncryptionWrapper(BaseEncryptionWrapper):
    """Wrapper that encrypts values before storing and decrypts on retrieval using Fernet (symmetric encryption)."""

    @overload
    def __init__(
        self,
        key_value: AsyncKeyValue,
        *,
        fernet: Fernet | MultiFernet,
        raise_on_decryption_error: bool = True,
    ) -> None:
        """Initialize the Fernet encryption wrapper.

        Args:
            key_value: The key-value store to wrap.
            fernet: The Fernet or MultiFernet instance to use for encryption and decryption MultiFernet is used to support
                    key rotation by allowing you to provide multiple Fernet instances that are attempted in order.
            raise_on_decryption_error: Whether to raise an exception if decryption fails. Defaults to True.
        """

    @overload
    def __init__(
        self,
        key_value: AsyncKeyValue,
        *,
        source_material: str,
        salt: str,
        raise_on_decryption_error: bool = True,
    ) -> None:
        """Initialize the Fernet encryption wrapper.

        Args:
            key_value: The key-value store to wrap.
            source_material: A string to use as the source material for the encryption key.
            salt: A string to use as the salt for the encryption key.
            raise_on_decryption_error: Whether to raise an exception if decryption fails. Defaults to True.
        """

    def __init__(
        self,
        key_value: AsyncKeyValue,
        *,
        fernet: Fernet | MultiFernet | None = None,
        source_material: str | None = None,
        salt: str | None = None,
        raise_on_decryption_error: bool = True,
    ) -> None:
        if fernet is not None:  # noqa: SIM102
            if source_material or salt:
                msg = "Cannot provide fernet together with source_material or salt"
                raise ValueError(msg)

        if fernet is None:
            if not source_material or not source_material.strip():
                msg = "Must provide either fernet or source_material"
                raise ValueError(msg)
            if not salt or not salt.strip():
                msg = "Must provide a salt"
                raise ValueError(msg)
            fernet = Fernet(key=_generate_encryption_key(source_material=source_material, salt=salt))

        def encrypt_with_fernet(data: bytes) -> bytes:
            return fernet.encrypt(data)

        def decrypt_with_fernet(data: bytes, encryption_version: int) -> bytes:
            if encryption_version > self.encryption_version:
                msg = f"Decryption failed: encryption versions newer than {self.encryption_version} are not supported"
                raise EncryptionVersionError(msg)
            return fernet.decrypt(data)

        super().__init__(
            key_value=key_value,
            encryption_fn=encrypt_with_fernet,
            decryption_fn=decrypt_with_fernet,
            encryption_version=ENCRYPTION_VERSION,
            raise_on_decryption_error=raise_on_decryption_error,
        )


def _generate_encryption_key(source_material: str, salt: str) -> bytes:
    """Generate a Fernet encryption key from a source material and salt using PBKDF2."""
    import base64

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    pbkdf2 = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt.encode(),
        iterations=KDF_ITERATIONS,
    ).derive(key_material=source_material.encode())

    return base64.urlsafe_b64encode(pbkdf2)
