"""FileTreeStore implementation using async filesystem operations."""

import contextlib
import os
import tempfile
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from aiofile import async_open as aopen
from anyio import Path as AsyncPath
from typing_extensions import Self, override

from key_value.aio._utils.managed_entry import ManagedEntry, dump_to_json, load_from_json
from key_value.aio._utils.sanitization import HashFragmentMode, HybridSanitizationStrategy, SanitizationStrategy
from key_value.aio._utils.sanitize import ALPHANUMERIC_CHARACTERS
from key_value.aio._utils.serialization import BasicSerializationAdapter, SerializationAdapter
from key_value.aio._utils.time_to_live import now
from key_value.aio.errors import PathSecurityError
from key_value.aio.stores.base import (
    BaseStore,
)

DIRECTORY_ALLOWED_CHARACTERS = ALPHANUMERIC_CHARACTERS + "_"

MAX_FILE_NAME_LENGTH = 255
FILE_NAME_ALLOWED_CHARACTERS = ALPHANUMERIC_CHARACTERS + "_"


MAX_PATH_LENGTH = 260


def get_max_path_length(root: Path | AsyncPath) -> int:
    """Get the maximum path length for the filesystem.

    Returns platform-specific limits:
    - Windows: 260 characters (MAX_PATH)
    - Unix/Linux: Uses pathconf to get PC_PATH_MAX
    """
    if os.name == "nt":  # Windows
        return MAX_PATH_LENGTH  # MAX_PATH on Windows

    reported_max_length = os.pathconf(path=Path(root), name="PC_PATH_MAX")
    if reported_max_length > 0:
        return reported_max_length
    return MAX_PATH_LENGTH


def get_max_file_name_length(root: Path | AsyncPath) -> int:
    """Get the maximum filename length for the filesystem.

    Returns platform-specific limits:
    - Windows: 255 characters
    - Unix/Linux: Uses pathconf to get PC_NAME_MAX
    """
    if os.name == "nt":  # Windows
        return MAX_FILE_NAME_LENGTH  # Maximum filename length on Windows (NTFS, FAT32, etc.)

    reported_max_length = os.pathconf(path=Path(root), name="PC_NAME_MAX")

    if reported_max_length > 0:
        return reported_max_length

    return MAX_FILE_NAME_LENGTH


@lru_cache(maxsize=1024)
def _validate_resolved_path_within_directory(resolved_path_str: str, resolved_root_str: str) -> bool:
    """Validate that a resolved path is within the resolved root directory (cached).

    This is a synchronous helper function that can be cached with LRU cache.
    The actual resolution is done by the async caller, and the resolved strings
    are passed here for the security check.

    Args:
        resolved_path_str: The resolved path as a string.
        resolved_root_str: The resolved root directory as a string.

    Returns:
        True if the path is within the root directory.

    Note:
        This function returns bool rather than raising to allow caching of valid paths.
        The caller is responsible for raising PathSecurityError if this returns False.
    """
    # Use is_relative_to for proper path containment check
    # Both paths are already resolved (symlinks followed, .. resolved) by the caller
    resolved_path = Path(resolved_path_str)
    resolved_root = Path(resolved_root_str)
    return resolved_path == resolved_root or resolved_path.is_relative_to(resolved_root)


async def validate_path_within_directory(path: AsyncPath, root_directory: AsyncPath) -> None:
    """Validate that a path is within the root directory.

    This prevents path traversal attacks where malicious keys like '../../../etc/passwd'
    could escape the data directory. The validation uses `resolve()` which also follows
    symlinks, so this catches symlink-based escapes as well.

    Args:
        path: The path to validate.
        root_directory: The root directory that path must be within.

    Raises:
        PathSecurityError: If the path escapes the root directory.
    """
    # Resolve paths first (follows symlinks)
    resolved_path = await path.resolve()
    resolved_root = await root_directory.resolve()

    # Convert to strings for the cached validation
    resolved_path_str = str(resolved_path)
    resolved_root_str = str(resolved_root)

    # Use the cached validation function
    if not _validate_resolved_path_within_directory(resolved_path_str, resolved_root_str):
        msg = f"Path '{path}' resolves outside the allowed directory '{root_directory}'"
        raise PathSecurityError(message=msg)


async def write_file_atomic(file: AsyncPath, text: str) -> None:
    """Write a file atomically using the write-to-temp-then-rename pattern.

    This ensures that the file is either fully written or not written at all,
    preventing data corruption on crash.

    The temporary file is created in the same directory as the target file
    to ensure the rename operation is atomic (same filesystem).

    Args:
        file: The target file path to write to.
        text: The text content to write.

    Note:
        The parent directory must exist before calling this function.
        Directory creation is handled by the collection setup logic.
    """
    # Get the directory of the target file
    dir_path = file.parent

    # Create a temporary file in the same directory (required for atomic rename)
    fd, temp_path_str = tempfile.mkstemp(dir=str(dir_path), suffix=".tmp")
    temp_path = Path(temp_path_str)

    # Close the fd immediately after mkstemp to avoid Windows file locking issues
    # and to prevent double-close errors. We'll reopen with aopen for async writing.
    os.close(fd)

    try:
        # Write content to the temporary file
        async with aopen(file_specifier=temp_path_str, mode="w", encoding="utf-8") as f:
            await f.write(data=text)
            # Flush Python buffers to OS and fsync to disk for durability
            await f.flush()
            os.fsync(f.file.fileno())

        # Atomically replace the target file with the temporary file
        temp_path.replace(Path(file))
    except BaseException:
        # Clean up the temporary file on any error
        # fd is already closed, so we just need to remove the temp file
        with contextlib.suppress(OSError):
            temp_path.unlink()
        raise


class FileTreeV1CollectionSanitizationStrategy(HybridSanitizationStrategy):
    """V1 sanitization strategy for FileTreeStore collections.

    This strategy ensures collection names are safe for filesystem use:
    - Alphanumeric values (plus underscore) are kept as-is for readability
    - Invalid characters are replaced with underscores
    - A hash fragment is added when sanitization occurs to prevent collisions

    Collection names (directories) are subject to the same length limit as file names (typically 255 bytes).
    The sanitized name is also used for the collection info file (with `-info.json` suffix), so we need
    to leave room for that suffix (10 characters).
    """

    def __init__(self, directory: Path | AsyncPath) -> None:
        # Directory names are subject to the same NAME_MAX limit as file names
        max_name_length: int = get_max_file_name_length(root=directory)

        # Leave room for `-info.json` suffix (10 chars) that's added to the metadata file name
        suffix_length = 10

        super().__init__(
            max_length=max_name_length - suffix_length,
            allowed_characters=DIRECTORY_ALLOWED_CHARACTERS,
            replacement_character="_",
            hash_fragment_mode=HashFragmentMode.ONLY_IF_CHANGED,
        )


class FileTreeV1KeySanitizationStrategy(HybridSanitizationStrategy):
    """V1 sanitization strategy for FileTreeStore keys.

    This strategy ensures key names are safe for filesystem use:
    - Alphanumeric values (plus underscore) are kept as-is for readability
    - Invalid characters are replaced with underscores
    - A hash fragment is added when sanitization occurs to prevent collisions
    """

    def __init__(self, directory: Path | AsyncPath) -> None:
        # We need to account for our current location in the filesystem to stay under the max path length
        max_path_length: int = get_max_path_length(root=directory)
        current_path_length: int = len(Path(directory).as_posix())
        remaining_length: int = max_path_length - current_path_length

        # We need to account for limits on file names
        max_file_name_length: int = get_max_file_name_length(root=directory) - 5  # 5 for .json extension

        # We need to stay under both limits
        super().__init__(
            max_length=min(remaining_length, max_file_name_length),
            allowed_characters=FILE_NAME_ALLOWED_CHARACTERS,
            replacement_character="_",
            hash_fragment_mode=HashFragmentMode.ONLY_IF_CHANGED,
        )


@dataclass(kw_only=True)
class DiskCollectionInfo:
    version: int = 1

    collection: str

    directory: AsyncPath

    # Root directory for security validation (path containment checks)
    root_directory: AsyncPath

    created_at: datetime

    serialization_adapter: SerializationAdapter
    key_sanitization_strategy: SanitizationStrategy

    async def _validate_path_security(self, path: AsyncPath) -> None:
        """Validate that a path is secure (within root directory).

        The validation uses `resolve()` which follows symlinks, so this catches
        symlink-based escapes as well as path traversal attacks.

        Args:
            path: The path to validate.

        Raises:
            PathSecurityError: If the path violates security boundaries.
        """
        await validate_path_within_directory(path=path, root_directory=self.root_directory)

    async def _list_file_paths(self) -> AsyncGenerator[AsyncPath]:
        async for item_path in AsyncPath(self.directory).iterdir():
            if not await item_path.is_file() or item_path.suffix != ".json":
                continue
            if item_path.stem == "info":
                continue
            yield item_path

    async def get_entry(self, *, key: str) -> ManagedEntry | None:
        sanitized_key = self.key_sanitization_strategy.sanitize(value=key)
        key_path: AsyncPath = AsyncPath(self.directory / f"{sanitized_key}.json")

        # Security validation
        await self._validate_path_security(path=key_path)

        if not await key_path.exists():
            return None

        data_dict: dict[str, Any] = await read_file(file=key_path)

        return self.serialization_adapter.load_dict(data=data_dict)

    async def put_entry(self, *, key: str, data: ManagedEntry) -> None:
        sanitized_key = self.key_sanitization_strategy.sanitize(value=key)
        key_path: AsyncPath = AsyncPath(self.directory / f"{sanitized_key}.json")

        # Security validation
        await self._validate_path_security(path=key_path)

        await write_file_atomic(file=key_path, text=self.serialization_adapter.dump_json(entry=data))

    async def delete_entry(self, *, key: str) -> bool:
        sanitized_key = self.key_sanitization_strategy.sanitize(value=key)
        key_path: AsyncPath = AsyncPath(self.directory / f"{sanitized_key}.json")

        # Security validation
        await self._validate_path_security(path=key_path)

        if not await key_path.exists():
            return False

        await key_path.unlink()

        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "collection": self.collection,
            "directory": str(self.directory),
            "created_at": self.created_at.isoformat(),
        }

    def to_json(self) -> str:
        return dump_to_json(obj=self.to_dict())

    @classmethod
    def from_dict(
        cls,
        *,
        data: dict[str, Any],
        root_directory: AsyncPath,
        serialization_adapter: SerializationAdapter,
        key_sanitization_strategy: SanitizationStrategy,
    ) -> Self:
        return cls(
            version=data["version"],
            collection=data["collection"],
            directory=AsyncPath(data["directory"]),
            root_directory=root_directory,
            created_at=datetime.fromisoformat(data["created_at"]),
            serialization_adapter=serialization_adapter,
            key_sanitization_strategy=key_sanitization_strategy,
        )

    @classmethod
    async def from_file(
        cls,
        *,
        file: AsyncPath,
        root_directory: AsyncPath,
        serialization_adapter: SerializationAdapter,
        key_sanitization_strategy: SanitizationStrategy,
    ) -> Self:
        if data := await read_file(file=file):
            resolved_directory = await AsyncPath(data["directory"]).resolve()
            data["directory"] = str(resolved_directory)
            return cls.from_dict(
                data=data,
                root_directory=root_directory,
                serialization_adapter=serialization_adapter,
                key_sanitization_strategy=key_sanitization_strategy,
            )

        msg = f"File {file} not found"

        raise FileNotFoundError(msg)

    @classmethod
    async def create_or_get_info(
        cls,
        *,
        data_directory: AsyncPath,
        metadata_directory: AsyncPath,
        root_directory: AsyncPath,
        collection: str,
        sanitized_collection: str,
        serialization_adapter: SerializationAdapter,
        key_sanitization_strategy: SanitizationStrategy,
    ) -> Self:
        info_file: AsyncPath = AsyncPath(metadata_directory / f"{sanitized_collection}-info.json")

        if await info_file.exists():
            return await cls.from_file(
                file=info_file,
                root_directory=root_directory,
                serialization_adapter=serialization_adapter,
                key_sanitization_strategy=key_sanitization_strategy,
            )

        info = cls(
            collection=collection,
            directory=data_directory,
            root_directory=root_directory,
            created_at=now(),
            serialization_adapter=serialization_adapter,
            key_sanitization_strategy=key_sanitization_strategy,
        )

        await write_file_atomic(file=info_file, text=info.to_json())
        return info


async def read_file(file: AsyncPath) -> dict[str, Any]:
    async with aopen(file_specifier=Path(file), mode="r", encoding="utf-8") as f:
        body: str = await f.read()
        return load_from_json(json_str=body)


class FileTreeStore(BaseStore):
    """A file-tree based store using directories for collections and files for keys.

    This store uses the native filesystem:
    - Each collection is a subdirectory under the base directory
    - Each key is stored as a JSON file named "{key}.json"
    - File contents contain the ManagedEntry serialized to JSON

    Directory structure:
        {base_directory}/
            {collection_1}/
                {key_1}.json
                {key_2}.json
            {collection_2}/
                {key_3}.json

    By default, collections and keys are not sanitized. This means that filesystem limitations
    on path lengths and special characters may cause errors when trying to get and put entries.

    To avoid issues, you may want to consider leveraging the `FileTreeV1CollectionSanitizationStrategy`
    and `FileTreeV1KeySanitizationStrategy` strategies.

    Security:
        This store includes the following security measures:
        - Path validation: All file paths are validated to stay within the data directory.
          The validation uses `resolve()` which follows symlinks, so symlink-based escapes
          are also detected and blocked.
        - Atomic writes: Files are written atomically using write-to-temp-then-rename with
          fsync for durability. This ensures data is not corrupted on system crash.

    Limitations:
        - No file locking: Concurrent writes to the same key from multiple processes may
          cause data loss (last write wins). Single-writer or external locking is recommended
          for multi-process scenarios.
        - No built-in cleanup of expired entries. Expired entries are only filtered out when
          read via get() or similar methods.
        - Performance may degrade with very large numbers of keys per collection due to
          filesystem directory entry limits.
    """

    _data_directory: AsyncPath
    _metadata_directory: AsyncPath

    _collection_infos: dict[str, DiskCollectionInfo]
    _auto_create: bool

    def __init__(
        self,
        *,
        data_directory: Path | str,
        metadata_directory: Path | str | None = None,
        default_collection: str | None = None,
        serialization_adapter: SerializationAdapter | None = None,
        key_sanitization_strategy: SanitizationStrategy | None = None,
        collection_sanitization_strategy: SanitizationStrategy | None = None,
        auto_create: bool = True,
    ) -> None:
        """Initialize the file-tree store.

        Args:
            data_directory: The base directory to use for storing collections and keys.
            metadata_directory: The directory to use for storing metadata. Defaults to data_directory.
            default_collection: The default collection to use if no collection is provided.
            serialization_adapter: The serialization adapter to use for the store.
            key_sanitization_strategy: The sanitization strategy to use for keys.
            collection_sanitization_strategy: The sanitization strategy to use for collections.
            auto_create: Whether to automatically create directories if they don't exist. Defaults to True.
                When False, raises ValueError if a directory doesn't exist.
        """
        data_directory = Path(data_directory).resolve()

        if not data_directory.exists():
            if not auto_create:
                msg = f"Directory '{data_directory}' does not exist. Either create the directory manually or set auto_create=True."
                raise ValueError(msg)
            data_directory.mkdir(parents=True, exist_ok=True)

        if metadata_directory is None:
            metadata_directory = data_directory

        metadata_directory = Path(metadata_directory).resolve()

        if not metadata_directory.exists():
            if not auto_create:
                msg = f"Directory '{metadata_directory}' does not exist. Either create the directory manually or set auto_create=True."
                raise ValueError(msg)
            metadata_directory.mkdir(parents=True, exist_ok=True)

        self._data_directory = AsyncPath(data_directory)
        self._metadata_directory = AsyncPath(metadata_directory)

        self._collection_infos = {}
        self._auto_create = auto_create

        super().__init__(
            serialization_adapter=serialization_adapter or BasicSerializationAdapter(),
            key_sanitization_strategy=key_sanitization_strategy,
            collection_sanitization_strategy=collection_sanitization_strategy,
            default_collection=default_collection,
            stable_api=True,
        )

    async def _get_data_directories(self) -> AsyncGenerator[AsyncPath]:
        async for directory in self._data_directory.iterdir():
            if await directory.is_dir():
                yield directory

    async def _get_metadata_entries(self) -> AsyncGenerator[AsyncPath]:
        async for entry in self._metadata_directory.iterdir():
            if await entry.is_file() and entry.suffix == ".json":
                yield await entry.resolve()

    async def _load_collection_infos(self) -> None:
        async for entry in self._get_metadata_entries():
            collection_info: DiskCollectionInfo = await DiskCollectionInfo.from_file(
                file=entry,
                root_directory=self._data_directory,
                serialization_adapter=self._serialization_adapter,
                key_sanitization_strategy=self._key_sanitization_strategy,
            )
            self._collection_infos[collection_info.collection] = collection_info

    @override
    async def _setup_collection(self, *, collection: str) -> None:
        """Set up a collection by creating its directory if it doesn't exist.

        Args:
            collection: The collection name.
        """
        if collection in self._collection_infos:
            return

        # Sanitize the collection name using the strategy
        sanitized_collection = self._sanitize_collection(collection=collection)

        # Create the collection directory under the data directory
        data_directory: AsyncPath = AsyncPath(self._data_directory / sanitized_collection)

        # Security validation BEFORE creating any directories
        # This prevents path traversal attacks where malicious collection names like
        # "../../../../tmp/evil" could create directories outside the data root
        await validate_path_within_directory(path=data_directory, root_directory=self._data_directory)

        if not await data_directory.exists():
            if not self._auto_create:
                msg = f"Directory '{data_directory}' does not exist. Either create the directory manually or set auto_create=True."
                raise ValueError(msg)
            await data_directory.mkdir(parents=True, exist_ok=True)

        self._collection_infos[collection] = await DiskCollectionInfo.create_or_get_info(
            data_directory=data_directory,
            metadata_directory=self._metadata_directory,
            root_directory=self._data_directory,
            collection=collection,
            sanitized_collection=sanitized_collection,
            serialization_adapter=self._serialization_adapter,
            key_sanitization_strategy=self._key_sanitization_strategy,
        )

    @override
    async def _get_managed_entry(self, *, key: str, collection: str) -> ManagedEntry | None:
        """Retrieve a managed entry by key from the specified collection.

        Args:
            collection: The collection name.
            key: The key name.

        Returns:
            The managed entry if found and not expired, None otherwise.
        """
        collection_info: DiskCollectionInfo = self._collection_infos[collection]

        return await collection_info.get_entry(key=key)

    @override
    async def _put_managed_entry(self, *, key: str, collection: str, managed_entry: ManagedEntry) -> None:
        """Store a managed entry at the specified key in the collection.

        Args:
            collection: The collection name.
            key: The key name.
            managed_entry: The managed entry to store.
        """
        collection_info: DiskCollectionInfo = self._collection_infos[collection]
        await collection_info.put_entry(key=key, data=managed_entry)

    @override
    async def _delete_managed_entry(self, *, key: str, collection: str) -> bool:
        """Delete a managed entry from the specified collection.

        Args:
            collection: The collection name.
            key: The key name.

        Returns:
            True if the entry was deleted, False if it didn't exist.
        """
        collection_info: DiskCollectionInfo = self._collection_infos[collection]

        return await collection_info.delete_entry(key=key)
