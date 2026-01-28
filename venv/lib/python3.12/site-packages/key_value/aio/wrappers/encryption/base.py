import base64
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any, SupportsFloat

from key_value.shared.errors.key_value import SerializationError
from key_value.shared.errors.wrappers.encryption import CorruptedDataError, DecryptionError, EncryptionError
from typing_extensions import override

from key_value.aio.protocols.key_value import AsyncKeyValue
from key_value.aio.wrappers.base import BaseWrapper

_ENCRYPTED_DATA_KEY = "__encrypted_data__"
_ENCRYPTION_VERSION_KEY = "__encryption_version__"


EncryptionFn = Callable[[bytes], bytes]
DecryptionFn = Callable[[bytes, int], bytes]


class BaseEncryptionWrapper(BaseWrapper):
    """Wrapper that encrypts values before storing and decrypts on retrieval.

    This wrapper encrypts the JSON-serialized value using a custom encryption function
    and stores it as a base64-encoded string within a special key in the dictionary.
    This allows encryption while maintaining the dict[str, Any] interface.
    """

    def __init__(
        self,
        key_value: AsyncKeyValue,
        encryption_fn: EncryptionFn,
        decryption_fn: DecryptionFn,
        encryption_version: int,
        raise_on_decryption_error: bool = True,
    ) -> None:
        """Initialize the encryption wrapper.

        Args:
            key_value: The store to wrap.
            encryption_fn: The encryption function to use. A callable that takes bytes and returns encrypted bytes.
            decryption_fn: The decryption function to use. A callable that takes bytes and an
                           encryption version int and returns decrypted bytes.
            encryption_version: The encryption version to use.
            raise_on_decryption_error: Whether to raise an exception if decryption fails. Defaults to True.
        """
        self.key_value: AsyncKeyValue = key_value
        self.raise_on_decryption_error: bool = raise_on_decryption_error

        self.encryption_version: int = encryption_version

        self._encryption_fn: EncryptionFn = encryption_fn
        self._decryption_fn: DecryptionFn = decryption_fn

        super().__init__()

    def _encrypt_value(self, value: dict[str, Any]) -> dict[str, Any]:
        """Encrypt a value into the encrypted format.

        The encrypted format looks like:
        {
            "__encrypted_data__": "base64-encoded-encrypted-data",
            "__encryption_version__": 1
        }
        """

        # Serialize to JSON
        try:
            json_str: str = json.dumps(value, separators=(",", ":"))

            json_bytes: bytes = json_str.encode(encoding="utf-8")
        except TypeError as e:
            msg: str = f"Failed to serialize object to JSON: {e}"
            raise SerializationError(msg) from e

        try:
            encrypted_bytes: bytes = self._encryption_fn(json_bytes)

            base64_str: str = base64.b64encode(encrypted_bytes).decode(encoding="ascii")
        except Exception as e:
            msg = "Failed to encrypt value"
            raise EncryptionError(msg) from e

        return {
            _ENCRYPTED_DATA_KEY: base64_str,
            _ENCRYPTION_VERSION_KEY: self.encryption_version,
        }

    def _validate_encrypted_payload(self, value: dict[str, Any]) -> tuple[int, str]:
        if _ENCRYPTION_VERSION_KEY not in value:
            msg = "missing encryption version key"
            raise CorruptedDataError(msg)

        encryption_version = value[_ENCRYPTION_VERSION_KEY]
        if not isinstance(encryption_version, int):
            msg = f"expected encryption version to be an int, got {type(encryption_version)}"
            raise CorruptedDataError(msg)

        if _ENCRYPTED_DATA_KEY not in value:
            msg = "missing encrypted data key"
            raise CorruptedDataError(msg)

        encrypted_data = value[_ENCRYPTED_DATA_KEY]

        if not isinstance(encrypted_data, str):
            msg = f"expected encrypted data to be a str, got {type(encrypted_data)}"
            raise CorruptedDataError(msg)

        return encryption_version, encrypted_data

    def _decrypt_value(self, value: dict[str, Any] | None) -> dict[str, Any] | None:
        """Decrypt a value from the encrypted format."""
        if value is None:
            return None

        # If the value is not actually encrypted, return it as-is
        if _ENCRYPTED_DATA_KEY not in value and isinstance(value, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
            return value

        try:
            encryption_version, encrypted_data = self._validate_encrypted_payload(value)

            encrypted_bytes: bytes = base64.b64decode(encrypted_data, validate=True)

            json_bytes: bytes = self._decryption_fn(encrypted_bytes, encryption_version)

            json_str: str = json_bytes.decode(encoding="utf-8")

            return json.loads(json_str)  # type: ignore[no-any-return]
        except CorruptedDataError:
            if self.raise_on_decryption_error:
                raise
            return None
        except Exception as e:
            msg = "Failed to decrypt value"
            if self.raise_on_decryption_error:
                raise DecryptionError(msg) from e
            return None

    @override
    async def get(self, key: str, *, collection: str | None = None) -> dict[str, Any] | None:
        value = await self.key_value.get(key=key, collection=collection)
        return self._decrypt_value(value)

    @override
    async def get_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[dict[str, Any] | None]:
        values = await self.key_value.get_many(keys=keys, collection=collection)
        return [self._decrypt_value(value) for value in values]

    @override
    async def ttl(self, key: str, *, collection: str | None = None) -> tuple[dict[str, Any] | None, float | None]:
        value, ttl = await self.key_value.ttl(key=key, collection=collection)
        return self._decrypt_value(value), ttl

    @override
    async def ttl_many(self, keys: Sequence[str], *, collection: str | None = None) -> list[tuple[dict[str, Any] | None, float | None]]:
        results = await self.key_value.ttl_many(keys=keys, collection=collection)
        return [(self._decrypt_value(value), ttl) for value, ttl in results]

    @override
    async def put(self, key: str, value: Mapping[str, Any], *, collection: str | None = None, ttl: SupportsFloat | None = None) -> None:
        encrypted_value = self._encrypt_value(dict(value))
        return await self.key_value.put(key=key, value=encrypted_value, collection=collection, ttl=ttl)

    @override
    async def put_many(
        self,
        keys: Sequence[str],
        values: Sequence[Mapping[str, Any]],
        *,
        collection: str | None = None,
        ttl: SupportsFloat | None = None,
    ) -> None:
        encrypted_values = [self._encrypt_value(dict(value)) for value in values]
        return await self.key_value.put_many(keys=keys, values=encrypted_values, collection=collection, ttl=ttl)
