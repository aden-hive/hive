"""Windows Registry-based key-value store."""

from typing import Literal
from winreg import HKEY_CURRENT_USER, HKEY_LOCAL_MACHINE

from key_value.shared.utils.managed_entry import ManagedEntry
from key_value.shared.utils.sanitization import HybridSanitizationStrategy, SanitizationStrategy
from key_value.shared.utils.sanitize import ALPHANUMERIC_CHARACTERS
from typing_extensions import override

from key_value.aio.stores.base import BaseStore

try:
    import winreg  # pyright: ignore[reportUnusedImport]  # noqa: F401

    from key_value.aio.stores.windows_registry.utils import create_key, delete_reg_sz_value, get_reg_sz_value, has_key, set_reg_sz_value
except ImportError as e:
    msg = "WindowsRegistryStore requires Windows platform (winreg module)"
    raise ImportError(msg) from e

DEFAULT_REGISTRY_PATH = "Software\\py-key-value"
DEFAULT_HIVE = "HKEY_CURRENT_USER"

MAX_COLLECTION_LENGTH = 96


class WindowsRegistryV1CollectionSanitizationStrategy(HybridSanitizationStrategy):
    def __init__(self) -> None:
        super().__init__(
            max_length=MAX_COLLECTION_LENGTH,
            allowed_characters=ALPHANUMERIC_CHARACTERS,
        )


class WindowsRegistryStore(BaseStore):
    """Windows Registry-based key-value store.

    This store uses the Windows Registry to persist key-value pairs. Each entry is stored
    as a string value in the registry under HKEY_CURRENT_USER\\Software\\{root}\\{collection}
    with the key being a registry reg_sz value named `{key}`.

    This store has specific restrictions on what is allowed in collections. Collections are not sanitized
    by default which may result in errors when using the store.

    To avoid issues, you may want to consider leveraging the `WindowsRegistryV1CollectionSanitizationStrategy`.

    Note: TTL is not natively supported by Windows Registry, so TTL information is stored
    within the JSON payload and checked at retrieval time. The store does not currently cull
    expired entries.
    """

    def __init__(
        self,
        *,
        hive: Literal["HKEY_CURRENT_USER", "HKEY_LOCAL_MACHINE"] | None = None,
        registry_path: str | None = None,
        default_collection: str | None = None,
        key_sanitization_strategy: SanitizationStrategy | None = None,
        collection_sanitization_strategy: SanitizationStrategy | None = None,
    ) -> None:
        """Initialize the Windows Registry store.

        Args:
            hive: The hive to use. Defaults to "HKEY_CURRENT_USER".
            registry_path: The registry path to use. Must be a valid registry path under the hive. Defaults to "Software\\py-key-value".
            default_collection: The default collection to use if no collection is provided.
            key_sanitization_strategy: The sanitization strategy to use for keys.
            collection_sanitization_strategy: The sanitization strategy to use for collections.
        """
        self._hive = HKEY_LOCAL_MACHINE if hive == "HKEY_LOCAL_MACHINE" else HKEY_CURRENT_USER
        self._registry_path = registry_path or DEFAULT_REGISTRY_PATH

        super().__init__(
            default_collection=default_collection,
            key_sanitization_strategy=key_sanitization_strategy,
            collection_sanitization_strategy=collection_sanitization_strategy,
        )

    def _get_registry_path(self, *, collection: str) -> str:
        """Get the full registry path for a collection."""
        sanitized_collection = self._sanitize_collection(collection=collection)
        return f"{self._registry_path}\\{sanitized_collection}"

    @override
    async def _setup_collection(self, *, collection: str) -> None:
        registry_path = self._get_registry_path(collection=collection)
        if not has_key(hive=self._hive, sub_key=registry_path):
            create_key(hive=self._hive, sub_key=registry_path)

    @override
    async def _get_managed_entry(self, *, key: str, collection: str) -> ManagedEntry | None:
        sanitized_key = self._sanitize_key(key=key)
        registry_path = self._get_registry_path(collection=collection)

        if not (json_str := get_reg_sz_value(hive=self._hive, sub_key=registry_path, value_name=sanitized_key)):
            return None

        return self._serialization_adapter.load_json(json_str=json_str)

    @override
    async def _put_managed_entry(self, *, key: str, collection: str, managed_entry: ManagedEntry) -> None:
        sanitized_key = self._sanitize_key(key=key)
        registry_path = self._get_registry_path(collection=collection)

        json_str: str = self._serialization_adapter.dump_json(entry=managed_entry, key=key, collection=collection)

        set_reg_sz_value(hive=self._hive, sub_key=registry_path, value_name=sanitized_key, value=json_str)

    @override
    async def _delete_managed_entry(self, *, key: str, collection: str) -> bool:
        sanitized_key = self._sanitize_key(key=key)
        registry_path = self._get_registry_path(collection=collection)

        return delete_reg_sz_value(hive=self._hive, sub_key=registry_path, value_name=sanitized_key)
