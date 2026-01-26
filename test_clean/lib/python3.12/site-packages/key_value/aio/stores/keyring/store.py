"""Python keyring-based key-value store."""

import os

from key_value.shared.errors.key_value import ValueTooLargeError
from key_value.shared.utils.compound import compound_key
from key_value.shared.utils.managed_entry import ManagedEntry
from key_value.shared.utils.sanitization import HybridSanitizationStrategy, SanitizationStrategy
from key_value.shared.utils.sanitize import ALPHANUMERIC_CHARACTERS
from typing_extensions import override

from key_value.aio.stores.base import BaseStore

try:
    import keyring
    from keyring.errors import PasswordDeleteError
except ImportError as e:
    msg = "KeyringStore requires py-key-value-aio[keyring]"
    raise ImportError(msg) from e

DEFAULT_KEYCHAIN_SERVICE = "py-key-value"


def is_value_too_large(value: bytes) -> bool:
    value_length = len(value)
    if os.name == "nt":
        return value_length > WINDOWS_MAX_VALUE_LENGTH
    return False


WINDOWS_MAX_VALUE_LENGTH = 2560  # bytes

MAX_KEY_COLLECTION_LENGTH = 256
ALLOWED_KEY_COLLECTION_CHARACTERS: str = ALPHANUMERIC_CHARACTERS


class KeyringV1KeySanitizationStrategy(HybridSanitizationStrategy):
    def __init__(self) -> None:
        super().__init__(
            replacement_character="_",
            max_length=MAX_KEY_COLLECTION_LENGTH,
            allowed_characters=ALLOWED_KEY_COLLECTION_CHARACTERS,
        )


class KeyringV1CollectionSanitizationStrategy(HybridSanitizationStrategy):
    def __init__(self) -> None:
        super().__init__(
            replacement_character="_",
            max_length=MAX_KEY_COLLECTION_LENGTH,
            allowed_characters=ALLOWED_KEY_COLLECTION_CHARACTERS,
        )


class KeyringStore(BaseStore):
    """Python keyring-based key-value store using keyring library.

    This store uses the system's keyring to persist key-value pairs. Each entry is stored
    as a password in the keychain with the combination of collection and key as the username.

    This store has specific restrictions on what is allowed in keys and collections. Keys and collections are not sanitized
    by default which may result in errors when using the store.

    To avoid issues, you may want to consider leveraging the `KeyringV1KeySanitizationStrategy`
    and `KeyringV1CollectionSanitizationStrategy` strategies.

    Note: TTL is not natively supported by Python keyring, so TTL information is stored
    within the JSON payload and checked at retrieval time.
    """

    _service_name: str

    def __init__(
        self,
        *,
        service_name: str = DEFAULT_KEYCHAIN_SERVICE,
        default_collection: str | None = None,
        key_sanitization_strategy: SanitizationStrategy | None = None,
        collection_sanitization_strategy: SanitizationStrategy | None = None,
    ) -> None:
        """Initialize the Python keyring store.

        Args:
            service_name: The service name to use in the keychain. Defaults to "py-key-value".
            default_collection: The default collection to use if no collection is provided.
            key_sanitization_strategy: The sanitization strategy to use for keys.
            collection_sanitization_strategy: The sanitization strategy to use for collections.
        """
        self._service_name = service_name

        super().__init__(
            default_collection=default_collection,
            collection_sanitization_strategy=collection_sanitization_strategy,
            key_sanitization_strategy=key_sanitization_strategy,
        )

    @override
    async def _get_managed_entry(self, *, key: str, collection: str) -> ManagedEntry | None:
        sanitized_collection = self._sanitize_collection(collection=collection)
        sanitized_key = self._sanitize_key(key=key)

        combo_key: str = compound_key(collection=sanitized_collection, key=sanitized_key)

        try:
            json_str: str | None = keyring.get_password(service_name=self._service_name, username=combo_key)
        except Exception:
            return None

        if json_str is None:
            return None

        return self._serialization_adapter.load_json(json_str=json_str)

    @override
    async def _put_managed_entry(self, *, key: str, collection: str, managed_entry: ManagedEntry) -> None:
        sanitized_collection = self._sanitize_collection(collection=collection)
        sanitized_key = self._sanitize_key(key=key)

        combo_key: str = compound_key(collection=sanitized_collection, key=sanitized_key)

        json_str: str = self._serialization_adapter.dump_json(entry=managed_entry, key=key, collection=collection)
        encoded_json_bytes: bytes = json_str.encode(encoding="utf-8")

        if is_value_too_large(value=encoded_json_bytes):
            raise ValueTooLargeError(size=len(encoded_json_bytes), max_size=2560, collection=sanitized_collection, key=sanitized_key)

        keyring.set_password(service_name=self._service_name, username=combo_key, password=json_str)

    @override
    async def _delete_managed_entry(self, *, key: str, collection: str) -> bool:
        sanitized_collection = self._sanitize_collection(collection=collection)
        sanitized_key = self._sanitize_key(key=key)

        combo_key: str = compound_key(collection=sanitized_collection, key=sanitized_key)

        try:
            keyring.delete_password(service_name=self._service_name, username=combo_key)
        except PasswordDeleteError:
            return False
        else:
            return True
